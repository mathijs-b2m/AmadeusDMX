// Amadeus Link's protocol against the engine's side (amadeus/show/link.py): the same bytes for the same inputs
// (the expected values were made by link.py itself), a pairing and a signed packet end to end, and, when the
// engine's Python is at hand, the engine's own receiver pairing with LinkNet and reading its decks.
using System.Diagnostics;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using AmadeusKit;
using Xunit.Abstractions;

namespace AmadeusKit.Tests;

public class LinkTests(ITestOutputHelper output)
{
    const string S = "00112233445566778899aabbccddeeff", C = "ffeeddccbbaa99887766554433221100";

    [Fact]
    public void TheCryptoMatchesLinkPy()
    {
        // python: link.proof("1234", s, c), link.session_key(...).hex(), link.sign(key, payload), link._h(key, "file", path).hex()
        Assert.Equal("3a4d8113d466dd21ce9216bba75eeb13b0a82607a127e87fadb4066fffa56fda", LinkProtocol.Proof("1234", S, C));
        var key = LinkProtocol.SessionKey("1234", S, C);
        Assert.Equal("01555b524476e7a9107de8d0fbcb92340388936d168a864549cd0c6d0299a7a8", LinkProtocol.Hex(key));
        var payload = Encoding.UTF8.GetBytes("""{"s":1,"ts":123456789,"d":{"t":81234,"master":1,"decks":[]}}""");
        Assert.Equal("06991910e2476dcecf4508abcd536728", LinkProtocol.Sign(key, payload));
        Assert.Equal("d548b671d13f9c73d85d959947785b3fdeab6970a845ed7c2da112750c1a29ee", LinkProtocol.FileAuth(key, "/Music/Café track.mp3"));
        Assert.Equal("e01c6d485d6583a767b56a17c2aa6d0a808784c6059414b0b4f414c18af5edc2", LinkProtocol.Hex(LinkProtocol.Hmac("0042", "pair", S, C)));
    }

    [Fact]
    public void PacketsAreFramedAndSigned()
    {
        var key = LinkProtocol.SessionKey("1234", S, C);
        var payload = LinkProtocol.Payload(1, 123456789, """{"t":81234,"master":1,"decks":[]}"""u8);
        Assert.Equal("""{"s":1,"ts":123456789,"d":{"t":81234,"master":1,"decks":[]}}""", Encoding.UTF8.GetString(payload));
        var packet = LinkProtocol.Signed(key, payload);
        Assert.EndsWith("|06991910e2476dcecf4508abcd536728", Encoding.UTF8.GetString(packet));
        Assert.Equal(payload, LinkProtocol.Verify(key, packet));
        packet[5] ^= 1;
        Assert.Null(LinkProtocol.Verify(key, packet));
        Assert.Null(LinkProtocol.Verify(LinkProtocol.SessionKey("9999", S, C), LinkProtocol.Signed(key, payload)));
        Assert.Matches("^[0-9]{4}$", LinkProtocol.NewCode());
        Assert.Matches("^[0-9a-f]{32}$", LinkProtocol.RandomHex());
    }

    static async Task<JsonElement> ReadLine(NetworkStream s)
    {
        var buf = new List<byte>();
        var one = new byte[1];
        while (await s.ReadAsync(one) == 1 && one[0] != '\n') buf.Add(one[0]);
        return J.ParseElement(buf.ToArray());
    }

    static Task Send(NetworkStream s, string json) => s.WriteAsync(Encoding.UTF8.GetBytes(json + "\n")).AsTask();

    [Fact]
    public async Task ALightingComputerPairsAndGetsSignedDecks()
    {
        using var net = new LinkNet { Code = "4321", Advertise = null };
        var peers = new TaskCompletionSource<IReadOnlyList<LinkNet.Peer>>();
        net.OnPeers = p => { if (p.Count > 0) peers.TrySetResult(p); };
        net.StartService(0, "test");
        while (net.ServicePort == 0) await Task.Delay(10);

        using var udp = new UdpClient(0);
        var udpPort = ((System.Net.IPEndPoint)udp.Client.LocalEndPoint!).Port;
        using var tcp = new TcpClient();
        await tcp.ConnectAsync("127.0.0.1", net.ServicePort);
        var s = tcp.GetStream();
        await Send(s, $$"""{"hello": "amadeus", "v": 1, "nonce": "{{C}}"}""");
        var hello = await ReadLine(s);
        Assert.Equal(1, hello.GetProperty("v").GetInt32());
        var sn = hello.GetProperty("nonce").GetString()!;
        await Send(s, $$"""{"proof": "{{LinkProtocol.Proof("4321", sn, C)}}", "udp": {{udpPort}}}""");
        var ok = await ReadLine(s);
        Assert.True(ok.GetProperty("ok").GetBoolean());
        var session = ok.GetProperty("session").GetString()!;
        Assert.Equal(12, session.Length);
        Assert.Single(await peers.Task.WaitAsync(TimeSpan.FromSeconds(5)));
        await Send(s, """{"ping": 7}""");
        Assert.Equal(7, (await ReadLine(s)).GetProperty("pong").GetInt32());

        // the plugin's packet goes out signed with the session key
        var file = Path.Combine(Path.GetTempPath(), $"amadeus-link-{Guid.NewGuid():N}.mp3");
        await File.WriteAllBytesAsync(file, [1, 2, 3, 4, 5]);
        try
        {
            net.Send(Encoding.UTF8.GetBytes($$"""{"t": 1, "master": 1, "decks": [{"deck": 1, "file": {{JsonSerializer.Serialize(file)}}, "pos": 1.5, "play": 1}]}"""));
            var got = await udp.ReceiveAsync().WaitAsync(TimeSpan.FromSeconds(5));
            var key = LinkProtocol.SessionKey("4321", sn, C);
            var payload = LinkProtocol.Verify(key, got.Buffer);
            Assert.NotNull(payload);
            var msg = J.ParseElement(payload!);
            Assert.Equal(1, msg.GetProperty("s").GetInt64());
            Assert.Equal(1.5, msg.GetProperty("d").GetProperty("decks")[0].GetProperty("pos").GetDouble());

            // a track it reported is served, with its hash; anything else is refused
            using (var t = new TcpClient())
            {
                await t.ConnectAsync("127.0.0.1", net.ServicePort);
                var ts = t.GetStream();
                await Send(ts, JsonSerializer.Serialize(new { file, session, auth = LinkProtocol.FileAuth(key, file) }));
                var head = await ReadLine(ts);
                Assert.True(head.GetProperty("ok").GetBoolean());
                Assert.Equal(5, head.GetProperty("size").GetInt32());
                Assert.Equal(LinkProtocol.Hex(System.Security.Cryptography.SHA256.HashData(new byte[] { 1, 2, 3, 4, 5 })),
                             head.GetProperty("sha256").GetString());
                var body = new byte[5];
                await ts.ReadExactlyAsync(body);
                Assert.Equal([1, 2, 3, 4, 5], body);
            }
            using (var t = new TcpClient())
            {
                await t.ConnectAsync("127.0.0.1", net.ServicePort);
                var ts = t.GetStream();
                await Send(ts, JsonSerializer.Serialize(new { file = "/etc/hosts", session, auth = LinkProtocol.FileAuth(key, "/etc/hosts") }));
                Assert.False((await ReadLine(ts)).GetProperty("ok").GetBoolean());
            }
        }
        finally { File.Delete(file); }
    }

    [Fact]
    public async Task AWrongCodeIsRefused()
    {
        using var net = new LinkNet { Code = "4321", Advertise = null };
        net.StartService(0, "test");
        while (net.ServicePort == 0) await Task.Delay(10);
        using var tcp = new TcpClient();
        await tcp.ConnectAsync("127.0.0.1", net.ServicePort);
        var s = tcp.GetStream();
        await Send(s, $$"""{"hello": "amadeus", "v": 1, "nonce": "{{C}}"}""");
        var sn = (await ReadLine(s)).GetProperty("nonce").GetString()!;
        await Send(s, $$"""{"proof": "{{LinkProtocol.Proof("1111", sn, C)}}", "udp": 9}""");
        var no = await ReadLine(s);
        Assert.False(no.GetProperty("ok").GetBoolean());
        Assert.Equal("wrong pairing code", no.GetProperty("error").GetString());
    }

    /// The engine's Python: AMADEUS_TEST_PYTHON, else the checkout's .venv (check.sh finds it).
    internal static string? EnginePython()
    {
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        foreach (var p in new[] { Environment.GetEnvironmentVariable("AMADEUS_TEST_PYTHON"), Workspace.VenvPython(root) })
            if (!string.IsNullOrEmpty(p) && File.Exists(p)) return p;
        return null;
    }

    [Fact]
    public async Task TheEnginesReceiverPairsAndReadsTheDecks()
    {
        if (EnginePython() is not { } python) { output.WriteLine("no engine Python: skipped"); return; }
        var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));
        using var net = new LinkNet { Code = "2468", Advertise = null };
        var served = 0;
        net.OnServed = () => Interlocked.Increment(ref served);
        net.StartService(0, "test");
        while (net.ServicePort == 0) await Task.Delay(10);
        using var cache = new TempWorkspace();
        cache.Write("track.mp3", "not really music");  // the receiver fetches the track before the deck counts
        var track = JsonSerializer.Serialize(Path.Combine(cache.Root, "track.mp3"));
        var script = $$"""
            import sys, time
            from pathlib import Path
            from amadeus.show.link import RemoteListener
            r = RemoteListener("127.0.0.1", {{net.ServicePort}}, "2468", Path(sys.argv[1]) / "cache")
            print("paired", flush=True)
            end = time.time() + 10
            while time.time() < end and not r.decks:
                time.sleep(0.05)
            print("decks", sorted(r.decks), r.master, flush=True)
            """;
        var psi = new ProcessStartInfo(python) { WorkingDirectory = root, RedirectStandardOutput = true, RedirectStandardError = true };
        psi.ArgumentList.Add("-c");
        psi.ArgumentList.Add(script);
        psi.ArgumentList.Add(cache.Root);
        psi.Environment["AMADEUS_DATA"] = cache.Root;
        using var p = Process.Start(psi)!;
        var stdout = p.StandardOutput;
        string? line;
        do line = await stdout.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(30));  // the engine says more on the way
        while (line is not null && line != "paired");
        if (line is null && (await p.StandardError.ReadToEndAsync()).Contains("ModuleNotFoundError"))
        {
            output.WriteLine("the engine's Python lacks its packages: skipped");
            return;
        }
        Assert.Equal("paired", line);
        var feeding = Task.Run(async () =>
        {
            for (var i = 0; i < 100 && !p.HasExited; i++)
            {
                net.Send(Encoding.UTF8.GetBytes($$"""{"t": 1, "master": 2, "decks": [{"deck": 2, "file": {{track}}, "pos": 10.0, "len": 300.0, "play": 1, "bpm": 128.0, "bpm0": 128.0, "vol": 1.0}]}"""));
                await Task.Delay(40);
            }
        });
        string? result;
        do result = await stdout.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(15));
        while (result is not null && !result.StartsWith("decks", StringComparison.Ordinal));
        await feeding;
        if (!p.HasExited) p.Kill();
        output.WriteLine(await p.StandardError.ReadToEndAsync());
        Assert.Equal("decks [2] 2", result);
        Assert.True(served > 0);
    }
}
