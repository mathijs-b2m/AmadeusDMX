// Amadeus Link's networking (LinkNet in mac/Sources/AmadeusLink/LinkServer.swift), here in the kit so it is tested
// against the engine's own receiver (amadeus/show/link.py) on any computer. It receives the DJ software's packets
// (UDP 127.0.0.1:9123, as a local engine would), pairs lighting computers with the 4-digit code, forwards every
// packet to them stamped with this computer's clock and signed, and serves them the tracks the DJ software has
// loaded (and only those). Never on the UI thread: the forwarding must stay on time; the callbacks come on any
// thread.
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace AmadeusKit;

public sealed class LinkNet : IDisposable
{
    public sealed record Peer(string Id, string Address, DateTime Since, int Packets);

    public string Code { get => Volatile.Read(ref _code); set => Volatile.Write(ref _code, value); }
    string _code = "0000";

    /// A summary of the decks (a few times a second) and the DJ software's name.
    public Action<string, string>? OnPlugin { get; set; }
    public Action<IReadOnlyList<Peer>>? OnPeers { get; set; }
    /// The service's trouble ("" once it's fine).
    public Action<string>? OnError { get; set; }
    /// The plugin's port: a message while it can't be opened, nil once it is.
    public Action<string?>? OnPluginError { get; set; }
    public Action? OnServed { get; set; }
    /// VirtualDJ's streamed tracks named from its database before they're passed on (the app's VirtualDJStreams).
    public Func<byte[], byte[]> Enrich { get; set; } = d => d;
    /// Advertises the service (DNS-SD on Windows); nil: not advertised (tests).
    public Func<string, int, IDisposable?>? Advertise { get; set; } =
        (name, port) => OperatingSystem.IsWindows() ? DnsSd.Register(name, LinkProtocol.ServiceType, port) : null;

    sealed class Session
    {
        public required byte[] Key;
        public required IPEndPoint Udp;
        public required TcpClient Control;
        public required string Address;
        public DateTime Since = DateTime.Now;
        public int Packets;
    }

    readonly Lock _lock = new();
    readonly Dictionary<string, Session> _sessions = [];
    readonly HashSet<string> _allowed = [];          // files the plugin has reported: the only ones served
    readonly Dictionary<string, (long Size, double Mtime, string Sha)> _hashes = [];
    long _seq;
    DateTime _lastSummary = DateTime.MinValue;
    readonly CancellationTokenSource _life = new();
    UdpClient? _plugin;
    readonly Socket _out = new(AddressFamily.InterNetworkV6, SocketType.Dgram, ProtocolType.Udp) { DualMode = true };
    CancellationTokenSource? _service;
    TcpListener? _listener;
    IDisposable? _advert;

    /// Whether the DJ software's plugin is what's passed on (another one is read by Amadeus Link itself).
    public bool PluginOn { get => Volatile.Read(ref _pluginOn); set => Volatile.Write(ref _pluginOn, value); }
    bool _pluginOn = true;

    /// The port the service listens on (0 until it does; the one asked for, or a free one for port 0).
    public int ServicePort { get; private set; }

    // MARK: the DJ software's plugin (local)

    /// Listens for the plugin on 127.0.0.1. Another program may hold the port (a lighting engine started on this
    /// laptop before Link): then it tries again every two seconds, until it's free.
    public void StartPlugin(int port) => _ = Task.Run(() => PluginLoop(port, _life.Token));

    async Task PluginLoop(int port, CancellationToken ct)
    {
        var busy = $"Port {port} is taken: the DJ software can't reach Link. Quit a lighting engine running on this laptop (Amadeus DMX's own live show); Link tries again by itself.";
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var udp = new UdpClient(new IPEndPoint(IPAddress.Loopback, port));
                _plugin = udp;
                OnPluginError?.Invoke(null);
                while (!ct.IsCancellationRequested)
                {
                    var r = await udp.ReceiveAsync(ct);
                    if (r.Buffer.Length > 0 && PluginOn) Forward(Enrich(r.Buffer));
                }
            }
            catch (SocketException)
            {
                OnPluginError?.Invoke(busy);
            }
            catch (OperationCanceledException) { return; }
            try { await Task.Delay(2000, ct); }
            catch (OperationCanceledException) { return; }
        }
    }

    /// A packet Amadeus Link made itself (djay Pro, Mixxx), passed on like the plugin's.
    public void Send(byte[] packet) => Forward(packet);

    /// One plugin packet: remember its files, then send it on, stamped and signed, to every lighting computer.
    void Forward(byte[] plugin)
    {
        var now = LinkProtocol.Now();
        string? summary = null, app = null;
        try
        {
            using var doc = JsonDocument.Parse(plugin);
            var root = doc.RootElement;
            if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("decks", out var decks) && decks.ValueKind == JsonValueKind.Array)
            {
                lock (_lock)
                    foreach (var d in decks.EnumerateArray())
                        if (d.ValueKind == JsonValueKind.Object && d.TryGetProperty("file", out var f) && f.ValueKind == JsonValueKind.String
                            && f.GetString() is { Length: > 0 } file) _allowed.Add(file);
                if ((DateTime.UtcNow - _lastSummary).TotalSeconds > 0.5)
                {
                    _lastSummary = DateTime.UtcNow;
                    summary = string.Join("\n", decks.EnumerateArray().Where(d => d.ValueKind == JsonValueKind.Object).Select(DeckLine));
                    app = root.TryGetProperty("app", out var a) && a.ValueKind == JsonValueKind.String ? a.GetString() : "VirtualDJ";
                }
            }
        }
        catch (JsonException) { }
        if (summary is not null) OnPlugin?.Invoke(summary, app ?? "VirtualDJ");

        List<(Session S, byte[] Packet)> sends;
        lock (_lock)
        {
            if (_sessions.Count == 0) return;
            var payload = LinkProtocol.Payload(++_seq, now, plugin);
            sends = _sessions.Values.Select(s => (s, LinkProtocol.Signed(s.Key, payload))).ToList();
            foreach (var (s, _) in sends) s.Packets++;
        }
        foreach (var (s, packet) in sends)
            try { _out.SendTo(packet, s.Udp); }
            catch (SocketException) { }
    }

    /// "1: ▶ track.mp3" for Link's window.
    static string DeckLine(JsonElement d)
    {
        string S(JsonElement o, string k) => o.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString()! : "";
        var file = S(d, "file");
        string name;
        if (d.TryGetProperty("stream", out var st) && st.ValueKind != JsonValueKind.Null)
        {
            var service = st.ValueKind == JsonValueKind.Object ? S(st, "service") : "";
            service = service.Length == 0 ? "Stream" : char.ToUpperInvariant(service[0]) + service[1..];
            name = $"{S(d, "artist")} – {S(d, "title")}  ({service}: the lighting computer fetches a copy)";
        }
        else name = file.Length == 0 ? "streamed, not named yet: dark" : file.Split('/', '\\').Last();
        var deck = d.TryGetProperty("deck", out var n) ? n.ToString() : "?";
        var play = d.TryGetProperty("play", out var p) && p.ValueKind == JsonValueKind.Number && p.GetDouble() == 1;
        return $"{deck}: {(play ? "▶" : "■")} {name}";
    }

    // MARK: the service (DNS-SD, pairing, tracks)

    /// Advertises Link and accepts lighting computers. A port that isn't free yet (Link just restarted) is tried
    /// again every two seconds, as long as Link is on.
    public void StartService(int port, string name)
    {
        StopService();
        var cts = new CancellationTokenSource();
        lock (_lock) _service = cts;
        _ = Task.Run(() => ServiceLoop(port, name, cts.Token));
    }

    async Task ServiceLoop(int port, string name, CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            TcpListener? l = null;
            try
            {
                l = new TcpListener(IPAddress.IPv6Any, port);
                l.Server.DualMode = true;
                l.Start();
                ServicePort = ((IPEndPoint)l.LocalEndpoint).Port;
                lock (_lock) { _listener = l; _advert = Advertise?.Invoke(name, ServicePort); }
                OnError?.Invoke("");
                while (!ct.IsCancellationRequested)
                {
                    var c = await l.AcceptTcpClientAsync(ct);
                    _ = Task.Run(() => Handle(c, ct));
                }
            }
            catch (SocketException e)
            {
                OnError?.Invoke($"Can’t advertise yet: {e.Message}. Trying again …");
            }
            catch (OperationCanceledException) { }
            catch (ObjectDisposedException) { }
            finally { l?.Stop(); }
            try { await Task.Delay(2000, ct); }
            catch (OperationCanceledException) { return; }
        }
    }

    public void StopService()
    {
        List<Session> old;
        lock (_lock)
        {
            _service?.Cancel();
            _service = null;
            _listener?.Stop();
            _listener = null;
            _advert?.Dispose();
            _advert = null;
            old = _sessions.Values.ToList();
            _sessions.Clear();
        }
        foreach (var s in old) s.Control.Close();
        Publish();
    }

    public void Drop(string id)
    {
        Session? s;
        lock (_lock) _sessions.Remove(id, out s);
        s?.Control.Close();
        Publish();
    }

    void Publish()
    {
        List<Peer> peers;
        lock (_lock) peers = _sessions.Select(p => new Peer(p.Key, p.Value.Address, p.Value.Since, p.Value.Packets)).OrderBy(p => p.Since).ToList();
        OnPeers?.Invoke(peers);
    }

    /// Reads JSON lines from a connection.
    sealed class Lines(NetworkStream stream)
    {
        readonly byte[] _buf = new byte[65536];
        readonly MemoryStream _pending = new();

        /// The next line as JSON, nil when the connection closed (or sent something that isn't JSON).
        public async Task<JsonElement?> Next(CancellationToken ct)
        {
            while (true)
            {
                var data = _pending.GetBuffer().AsSpan(0, (int)_pending.Length);
                var nl = data.IndexOf((byte)'\n');
                if (nl >= 0)
                {
                    var line = data[..nl].ToArray();
                    var rest = data[(nl + 1)..].ToArray();
                    _pending.SetLength(0);
                    _pending.Write(rest);
                    try
                    {
                        using var doc = JsonDocument.Parse(line);
                        return doc.RootElement.ValueKind == JsonValueKind.Object ? doc.RootElement.Clone() : null;
                    }
                    catch (JsonException) { return null; }
                }
                var n = await stream.ReadAsync(_buf, ct);
                if (n == 0) return null;
                _pending.Write(_buf, 0, n);
                if (_pending.Length > 1 << 20) return null;
            }
        }
    }

    static async Task SendLine(NetworkStream s, object obj, CancellationToken ct)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(obj, obj.GetType(), SetupAPI.JsonOptions);
        await s.WriteAsync(bytes, ct);
        await s.WriteAsync("\n"u8.ToArray(), ct);
    }

    static string? Str(JsonElement o, string k) => o.TryGetProperty(k, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    async Task Handle(TcpClient c, CancellationToken ct)
    {
        c.NoDelay = true;
        var stream = c.GetStream();
        var lines = new Lines(stream);
        try
        {
            if (await lines.Next(ct) is not { } first) { c.Close(); return; }
            if (first.TryGetProperty("file", out _)) { await ServeFile(c, stream, first, ct); return; }
            if (Str(first, "hello") != "amadeus" || Str(first, "nonce") is not { } cn) { c.Close(); return; }
            var sn = LinkProtocol.RandomHex();
            await SendLine(stream, new { v = LinkProtocol.Version, name = Dns.GetHostName(), nonce = sn }, ct);
            var msg = await lines.Next(ct);
            var code = Code;
            if (msg is not { } m || Str(m, "proof") is not { } proof || !m.TryGetProperty("udp", out var udpEl)
                || !udpEl.TryGetInt32(out var udpPort) || udpPort is <= 0 or > 65535
                || !CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(proof), Encoding.ASCII.GetBytes(LinkProtocol.Proof(code, sn, cn))))
            {
                await SendLine(stream, new { ok = false, error = "wrong pairing code" }, ct);
                c.Close();
                return;
            }
            var key = LinkProtocol.SessionKey(code, sn, cn);
            var id = LinkProtocol.RandomHex()[..12];
            var remote = (IPEndPoint)c.Client.RemoteEndPoint!;
            var host = remote.Address.IsIPv4MappedToIPv6 ? remote.Address.MapToIPv4() : remote.Address;
            var to = new IPEndPoint(host.AddressFamily == AddressFamily.InterNetwork ? host.MapToIPv6() : host, udpPort);
            lock (_lock) _sessions[id] = new Session { Key = key, Udp = to, Control = c, Address = host.ToString() };
            await SendLine(stream, new { ok = true, session = id }, ct);
            Publish();
            // the keepalive: pings answered until the connection drops
            while (await lines.Next(ct) is { } ping)
                if (ping.TryGetProperty("ping", out var n)) await SendLine(stream, new { pong = JSONValue.From(n) }, ct);
            lock (_lock) _sessions.Remove(id);
            Publish();
        }
        catch (Exception e) when (e is IOException or SocketException or OperationCanceledException or ObjectDisposedException)
        {
            bool gone;
            lock (_lock)
            {
                var mine = _sessions.Where(p => p.Value.Control == c).Select(p => p.Key).ToList();
                foreach (var k in mine) _sessions.Remove(k);
                gone = mine.Count > 0;
            }
            if (gone) Publish();
        }
        finally { c.Close(); }
    }

    async Task ServeFile(TcpClient c, NetworkStream stream, JsonElement req, CancellationToken ct)
    {
        Session? s = null;
        var path = Str(req, "file");
        var sid = Str(req, "session");
        lock (_lock) if (sid is not null) _sessions.TryGetValue(sid, out s);
        if (path is null || s is null || Str(req, "auth") is not { } auth || auth != LinkProtocol.FileAuth(s.Key, path))
        {
            await SendLine(stream, new { ok = false, error = "not allowed" }, ct);
            return;
        }
        bool allowed;
        lock (_lock) allowed = _allowed.Contains(path);
        byte[] data;
        double mtime;
        try
        {
            if (!allowed) throw new FileNotFoundException();
            data = await File.ReadAllBytesAsync(path, ct);
            mtime = (File.GetLastWriteTimeUtc(path) - DateTime.UnixEpoch).TotalSeconds;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            await SendLine(stream, new { ok = false, error = "not a track the DJ software has loaded" }, ct);
            return;
        }
        string sha;
        lock (_lock)
        {
            if (_hashes.TryGetValue(path, out var h) && h.Size == data.Length && h.Mtime == mtime) sha = h.Sha;
            else
            {
                sha = LinkProtocol.Hex(SHA256.HashData(data));
                _hashes[path] = (data.Length, mtime, sha);
            }
        }
        await SendLine(stream, new { ok = true, size = data.Length, mtime, sha256 = sha }, ct);
        await stream.WriteAsync(data, ct);
        OnServed?.Invoke();
    }

    public void Dispose()
    {
        StopService();
        _life.Cancel();
        _plugin?.Dispose();
        _out.Dispose();
    }
}
