// Mixxx on the DJ laptop: its official controller scripting, through a MIDI port called "Amadeus DMX" (a port of
// mac/Sources/AmadeusLink/DJ/Mixxx.swift and amadeus/show/sources/mixxx.py). In Mixxx (Preferences › Controllers)
// that port gets the "Amadeus DMX" mapping (mixxx/ in the repository, carried by Link and copied into Mixxx's
// controllers folder), whose script sends every deck's state 50 times a second as SysEx. A script can't read a
// track's title or file: the track is found in Mixxx's library by its length in samples.
//
// The port itself is the app's (Windows: a Windows MIDI Services loopback or a loopMIDI port, read with WinMM:
// AmadeusLink/DJ/WinMidi.cs); it hands every SysEx message to `Message`. Mixxx looks for MIDI devices only when it
// starts: start Mixxx after the port is there.
using Microsoft.Data.Sqlite;

namespace AmadeusKit.DJ;

/// The MIDI port can't be opened: what to tell the DJ.
public sealed class MidiPortException(string message) : Exception(message);

public sealed class MixxxReader : IDJReader
{
    public string App => "Mixxx";
    public const string Name = "Amadeus DMX";
    public static readonly byte[] Header = [0xF0, 0x7D, 0x44, 0x4C, 0x01];
    public const double LoadingS = 0.3;  // while Mixxx loads a track its position is briefly meaningless

    /// Where Mixxx keeps its settings: sandboxed (the macOS download), not sandboxed, Linux, Windows (%LOCALAPPDATA%).
    public static IReadOnlyList<string> SettingsPlaces()
    {
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return
        [
            Path.Combine(home, "Library", "Containers", "org.mixxx.mixxx", "Data", "Library", "Application Support", "Mixxx"),
            Path.Combine(home, "Library", "Application Support", "Mixxx"),
            Path.Combine(home, ".mixxx"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Mixxx"),
        ];
    }

    public static string? Settings(IReadOnlyList<string>? places = null) => (places ?? SettingsPlaces()).FirstOrDefault(Directory.Exists);

    readonly Lock _lock = new();
    readonly Dictionary<int, Dictionary<string, double>> _state = [];
    double _xfader;
    readonly string _portError = "";
    readonly IDisposable? _port;
    readonly MixxxLibrary _library;
    readonly Resolver _resolver;

    /// The port's name as the system calls it, "" while there is none.
    public string PortName { get; } = "";
    /// SysEx messages Mixxx's script sent that never arrived (its sequence numbers skipped).
    public int Lost { get; private set; }
    int _seq = -1;

    /// `open` opens the port and hands it every SysEx message (F0 … F7); it says the port's name. It throws
    /// MidiPortException when there is no port to open.
    public MixxxReader(Func<Action<byte[]>, (IDisposable Port, string Name)>? open, string? mapping = null, string? settings = null,
                       Resolver? resolver = null)
    {
        settings ??= Settings();
        _library = new MixxxLibrary(settings is null ? null : Path.Combine(settings, "mixxxdb.sqlite"));
        _resolver = resolver ?? new Resolver();
        if (mapping is not null && settings is not null) InstallMapping(mapping, settings);
        if (open is null) return;
        try { (_port, PortName) = open(m => Message(m, Clock.Monotonic())); }
        catch (MidiPortException e) { _portError = e.Message; }
    }

    public string Note
    {
        get
        {
            lock (_lock)
            {
                if (_portError.Length > 0) return _portError;
                if (_state.Count == 0)
                    return $"In Mixxx: Preferences › Controllers › {Name}, mapping \"{Name}\", enabled. Start Mixxx after Amadeus Link.";
                return "";
            }
        }
    }

    public void Stop() => _port?.Dispose();

    /// Copies our mapping into Mixxx's controllers folder (Mixxx reads it at its next start). Where it went, nil
    /// when it couldn't.
    public static string? InstallMapping(string ours, string settings)
    {
        var dest = Path.Combine(settings, "controllers");
        try
        {
            Directory.CreateDirectory(dest);
            foreach (var f in Directory.EnumerateFiles(ours).Where(f => Path.GetExtension(f) is ".xml" or ".js"))
            {
                var to = Path.Combine(dest, Path.GetFileName(f));
                var mine = File.ReadAllBytes(f);
                if (Files.ReadBytes(to) is { } there && there.AsSpan().SequenceEqual(mine)) continue;
                File.Copy(f, to, overwrite: true);
            }
            return dest;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }

    /// One SysEx message from the port.
    public void Message(byte[] msg, double now)
    {
        if (Decode(msg) is not { } m) return;
        lock (_lock)
        {
            if (m.TryGetValue("xfader", out var x)) { _xfader = x; return; }
            var seq = (int)m["seq"];
            if (_seq >= 0) Lost += ((seq - _seq - 1) % 16384 + 16384) % 16384;
            _seq = seq;
            var deck = (int)m["deck"];
            m["at"] = now;
            _state.TryGetValue(deck, out var old);
            var newTrack = old is null || old["samples"] != m["samples"] || old["rate"] != m["rate"];
            m["since"] = newTrack ? now : old!["since"];
            _state[deck] = m;
        }
    }

    static int U7(ReadOnlySpan<byte> b, int i, int n)
    {
        var v = 0;
        foreach (var x in b.Slice(i, n)) v = v * 128 + x;
        return v;
    }

    /// One SysEx message from the script (format in mixxx/Amadeus-DMX-scripts.js) → its numbers.
    public static Dictionary<string, double>? Decode(ReadOnlySpan<byte> msg)
    {
        if (msg.Length <= Header.Length || !msg[..Header.Length].SequenceEqual(Header) || msg[^1] != 0xF7) return null;
        var body = msg[Header.Length..^1];
        if (body.Length >= 3 && body[0] == 0x02) return new() { ["xfader"] = U7(body, 1, 2) / 16383.0 * 2 - 1 };
        if (body.Length < 28 || body[0] != 0x01) return null;
        int flags = body[2];
        return new()
        {
            ["deck"] = body[1], ["play"] = flags & 1, ["loop"] = (flags >> 2) & 1, ["orientation"] = (flags >> 3) & 3,
            ["pos"] = (U7(body, 3, 5) - (1 << 30)) / 1000.0, ["samples"] = U7(body, 8, 5), ["rate"] = U7(body, 13, 3),
            ["ratio"] = (U7(body, 16, 4) - (1 << 27)) / 1e6, ["bpm"] = U7(body, 20, 4) / 1000.0, ["vol"] = U7(body, 24, 2) / 16383.0,
            ["seq"] = U7(body, 26, 2),
        };
    }

    /// Mixxx's crossfader (-1 left .. 1 right) → a deck's gain; orientation 0 left, 1 centre, 2 right.
    public static double XfadeGain(double x, int orientation)
    {
        if (orientation == 1) return 1;
        var far = orientation == 0 ? x : -x;  // how far towards the other side
        return far > 0 ? Math.Min(1, 1 - far) : 1;
    }

    public IReadOnlyList<DeckReading> Decks(double now)
    {
        List<(int N, Dictionary<string, double> M)> s;
        double x;
        lock (_lock)
        {
            s = [.. _state.OrderBy(p => p.Key).Select(p => (p.Key, p.Value))];
            x = _xfader;
        }
        List<DeckReading> out_ = [];
        foreach (var (n, m) in s)
        {
            if (now - m["at"] > 1 || now - m["since"] < LoadingS) continue;  // unloaded, or loading
            var samples = (long)m["samples"];
            var rate = (int)m["rate"];
            var bpm = m["bpm"];
            var t = _library.Find(samples, rate, bpm);
            var file = t.File.Length == 0 ? "" : _resolver.Find(t.File, t.Artist, t.Title);
            var ratio = m["ratio"] == 0 ? 1 : m["ratio"];
            var play = m["play"] == 1;
            out_.Add(new DeckReading
            {
                Deck = n, File = file, Pos = m["pos"], Length = rate > 0 ? samples / 2.0 / rate : 0, Play = play, Bpm = bpm,
                Bpm0 = bpm > 0 ? bpm / ratio : 0, Vol = m["vol"] * XfadeGain(x, (int)m["orientation"]), Received = m["at"],
                Title = t.Title, Artist = t.Artist, Id = $"{samples}@{rate}", Rate = play ? ratio : 0,
            });
        }
        return out_;
    }

    public string Summary(double now) => string.Join("\n", Decks(now).Select(d => d.Line));
}

/// Mixxx's track library (mixxxdb.sqlite, read only): which track is this many samples at this rate.
public sealed class MixxxLibrary(string? path)
{
    readonly Lock _lock = new();
    readonly Dictionary<string, (string File, string Artist, string Title)> _memo = [];

    /// Mixxx counts samples in stereo (frames × 2) whatever the file has.
    public (string File, string Artist, string Title) Find(long samples, int rate, double bpm)
    {
        var key = $"{samples}@{rate}";
        lock (_lock) if (_memo.TryGetValue(key, out var hit)) return hit;
        var found = (File: "", Artist: "", Title: "");
        if (path is null || rate <= 0 || !File.Exists(path)) return found;
        try
        {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            db.Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = "SELECT l.location, t.artist, t.title, t.bpm FROM library t JOIN track_locations l ON l.id = t.location "
                + "WHERE t.samplerate = $rate AND abs(t.duration - $len) < 0.05 AND t.mixxx_deleted = 0";
            cmd.Parameters.AddWithValue("$rate", rate);
            cmd.Parameters.AddWithValue("$len", samples / 2.0 / rate);
            using var r = cmd.ExecuteReader();
            var best = double.PositiveInfinity;
            while (r.Read())
            {
                string S(int i) => r.IsDBNull(i) ? "" : r.GetString(i);
                var d = Math.Abs((r.IsDBNull(3) ? 0 : r.GetDouble(3)) - bpm);
                if (d < best) { best = d; found = (S(0), S(1), S(2)); }
            }
        }
        catch (SqliteException) { return found; }
        lock (_lock) _memo[key] = found;
        return found;
    }
}

/// WinMM's SysEx buffers → whole messages (F0 … F7), also when one spans two buffers (winmidi.py SysEx).
public sealed class SysExAssembler
{
    readonly List<byte> _part = [];

    public List<byte[]> Feed(ReadOnlySpan<byte> data)
    {
        List<byte[]> out_ = [];
        foreach (var b in data)
        {
            if (b == 0xF0) { _part.Clear(); _part.Add(b); }
            else if (_part.Count > 0)
            {
                _part.Add(b);
                if (b == 0xF7) { out_.Add([.. _part]); _part.Clear(); }
            }
        }
        return out_;
    }
}

public static class MidiPorts
{
    /// The port called `wanted`: exactly; else one the system names with something added: at the front ("IAC Driver
    /// Bus 1" for "Bus 1"), at the end on Windows ("Amadeus DMX 1", "Amadeus DMX group 1") (`loose`). As winmidi.py.
    public static int? Matching(IReadOnlyList<string> names, string wanted, bool loose = true)
    {
        List<Func<string, bool>> tests = [n => n == wanted, n => n.EndsWith(" " + wanted, StringComparison.Ordinal)];
        if (loose) tests.Add(n => n.StartsWith(wanted + " ", StringComparison.Ordinal));
        foreach (var test in tests)
            for (var i = 0; i < names.Count; i++)
                if (test(names[i])) return i;
        return null;
    }
}
