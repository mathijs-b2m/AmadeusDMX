// djay Pro on the DJ laptop: what its window says, read like a screen reader would (a port of
// mac/Sources/AmadeusLink/DJ/Djay.swift and amadeus/show/sources/djay.py: the same labels, the same playhead, the
// same library lookup). How the window is read is the app's (Windows: UI Automation, AmadeusLink/DJ/UiaWindow.cs):
// an IDjayWindow gives the labelled controls and their values as text, the rest is here, tested on any computer.
//
// Amadeus Link only reads: djay's window, and the text of its deck controls. It never clicks, types or changes
// anything. A deck on SYNC is marked so; the lighting computer reads the exact beat from Ableton Link itself.
using System.Globalization;
using Microsoft.Data.Sqlite;

namespace AmadeusKit.DJ;

/// djay's labels for its deck controls: VoiceOver's on macOS, Narrator's (UI Automation names) on Windows. The
/// same words as the engine's (amadeus/show/sources/djay.py): change them together.
public static class DjayLabels
{
    public const string Decks = "Decks";  // the group they are in
    public const string Elapsed = "Elapsed time", Remaining = "Remaining time", Play = "Play / Pause", Title = "Title", Artist = "Artist";
    public const string Volume = "Line volume", Tempo = "Tempo", Sync = "Sync", Crossfader = "Crossfader";
    public const string Active = "Active";  // a pressed play or sync button

    /// "Elapsed time", 1 → "Elapsed time, Deck 1".
    public static string Label(string control, int deck) => $"{control}, Deck {deck}";

    /// A label of one of the controls we read (the rest of djay's window is left alone).
    public static bool Wanted(string label) => label == Crossfader || label.Contains(", Deck ", StringComparison.Ordinal);

    /// A control's value in the words macOS's Accessibility API uses, from what UI Automation gives: its value text
    /// as it is; a toggle (play, sync) as "Active"; a fader as a percentage (the tempo fader in its own percent, the
    /// others as the share of their range). As djay.py uia_text.
    public static string? UiaText(string? value = null, int? toggle = null, (double Value, double Min, double Max)? range = null, string label = "")
    {
        if (!string.IsNullOrEmpty(value)) return value;
        if (toggle is { } t) return t == 1 ? Active : "Inactive";
        if (range is { } r)
        {
            if (label.StartsWith(Tempo, StringComparison.Ordinal)) return G(r.Value) + "%";
            return r.Max > r.Min ? G(100 * (r.Value - r.Min) / (r.Max - r.Min)) + "%" : null;
        }
        return null;
    }

    /// Python's "{:g}": six significant digits, no trailing zeros.
    static string G(double v) => v.ToString("G6", CultureInfo.InvariantCulture);
}

/// How djay's window is read (Windows: UI Automation). Only reading: no method here changes anything.
public interface IDjayWindow<T>
{
    /// Called first on every thread that reads (Windows: COM).
    void Attach();
    /// djay's deck controls by their labels (only the wanted ones); empty when djay isn't there.
    Dictionary<string, List<T>> Scan();
    /// One control's value as text, nil when it has none (or is gone).
    string? Read(T control);
    /// What the DJ should know about reading the window ("" when nothing): e.g. djay runs but shows no labels we know.
    string Note { get; }
}

/// djay's deck controls by their labels, with what the labels themselves say: the deck numbers
/// ("Elapsed time, Deck 1") and each deck's tempo (its tempo button is labelled "125.0, Deck 1").
public sealed class Controls<T>
{
    public Dictionary<string, List<T>> Labels { get; }
    public IReadOnlyList<int> Decks { get; }
    public IReadOnlyDictionary<int, double> Bpm { get; }

    public Controls(Dictionary<string, List<T>>? labels = null)
    {
        Labels = labels ?? [];
        SortedSet<int> decks = [];
        Dictionary<int, double> bpm = [];
        foreach (var k in Labels.Keys)
        {
            var at = k.LastIndexOf(", Deck ", StringComparison.Ordinal);
            if (at < 0 || !int.TryParse(k.AsSpan(at + 7), NumberStyles.None, CultureInfo.InvariantCulture, out var n)) continue;
            var head = k[..at];
            if (head == DjayLabels.Elapsed) decks.Add(n);
            else if (double.TryParse(head, NumberStyles.AllowDecimalPoint, CultureInfo.InvariantCulture, out var b)) bpm[n] = b;
        }
        Decks = [.. decks];
        Bpm = bpm;
    }
}

/// djay Pro, read from its window: the playhead 200 times a second, the rest five times a second.
public sealed class DjayReader<T> : IDJReader
{
    public string App => "djay Pro";

    /// djay's library (MediaLibrary.db, read only): in the Music folder's djay folder, in its bundle (macOS) or a
    /// plain folder (djay Pro for Windows). As djay.py library_places.
    public static IReadOnlyList<string> LibraryPlaces()
    {
        var djay = Path.Combine(Paths.UserFolder(Environment.SpecialFolder.MyMusic, "Music"), "djay");
        return [Path.Combine(djay, "djay Media Library.djayMediaLibrary", "MediaLibrary.db"), Path.Combine(djay, "djay Media Library", "MediaLibrary.db")];
    }

    public static string LibraryFile() => LibraryPlaces().FirstOrDefault(File.Exists) ?? LibraryPlaces()[0];

    sealed class Info
    {
        public string Title = "", Artist = "", File = "";
        public double Length, Bpm;
        public double? Vol;
        public bool Sync;
        public StreamedTrack? Stream;
    }

    readonly Lock _lock = new();
    readonly IDjayWindow<T> _window;
    volatile bool _running = true;
    Controls<T> _controls = new();
    readonly Dictionary<int, Playhead> _heads = [];
    readonly Dictionary<int, Info> _info = [];
    double _xfader = 0.5;
    bool _found;
    HashSet<int> _streamed = [];
    readonly Resolver _resolver;
    readonly DjayLibrary _tracks;
    readonly DjayStreams _streamsKnown;

    public DjayReader(IDjayWindow<T> window, string? library = null, Resolver? resolver = null)
    {
        _window = window;
        library ??= LibraryFile();
        _tracks = new DjayLibrary(library);
        _streamsKnown = new DjayStreams(library);
        _resolver = resolver ?? new Resolver();
        _tracks.Read();
        _resolver.Add(_tracks.Folders);
        new Thread(ScanLoop) { IsBackground = true, Name = "djay scan" }.Start();
        new Thread(ReadLoop) { IsBackground = true, Name = "djay read", Priority = ThreadPriority.AboveNormal }.Start();
    }

    public string Note
    {
        get
        {
            lock (_lock)
            {
                if (!_found) return _window.Note is { Length: > 0 } n ? n : "Waiting for djay Pro.";
                if (_streamed.Count > 0) return "A track on a deck is neither a file here nor a stream djay's library knows: it stays dark.";
                return "";
            }
        }
    }

    public void Stop() => _running = false;

    // MARK: finding djay's controls (never in the way of the playhead)

    void ScanLoop()
    {
        _window.Attach();
        while (_running)
        {
            Controls<T> found;
            try { found = new Controls<T>(_window.Scan()); }
            catch (Exception) { found = new Controls<T>(); }  // djay quit or redrew its window meanwhile
            lock (_lock)
            {
                _controls = found;
                _found = found.Labels.Count > 0;
            }
            Thread.Sleep(found.Labels.Count == 0 ? 500 : 2000);
        }
    }

    string? Value(Controls<T> c, string label)
    {
        if (!c.Labels.TryGetValue(label, out var es) || es.Count == 0) return null;
        try { return _window.Read(es[0]); }
        catch (Exception) { return null; }
    }

    // MARK: reading

    void ReadLoop()
    {
        _window.Attach();
        var slow = 0.0;
        while (_running)
        {
            Controls<T> c;
            lock (_lock) c = _controls;
            if (c.Labels.Count == 0)
            {
                Thread.Sleep(200);
                continue;
            }
            var now = Clock.Monotonic();
            if (now - slow > 0.2)  // what changes slowly: track, tempo, faders
            {
                slow = now;
                ReadSlow(c, now);
            }
            foreach (var n in c.Decks)  // what must be on time: the playhead
            {
                var play = Value(c, DjayLabels.Label(DjayLabels.Play, n)) == DjayLabels.Active;
                var secs = Djay.Clock(Value(c, DjayLabels.Label(DjayLabels.Elapsed, n)));
                lock (_lock)
                {
                    var head = Head(n);
                    head.SetPlay(play, now);
                    if (secs is { } s && s != head.Label) head.Seen(s, Clock.Monotonic());
                }
            }
            Thread.Sleep(5);
        }
    }

    Playhead Head(int n)
    {
        if (!_heads.TryGetValue(n, out var h)) _heads[n] = h = new Playhead();
        return h;
    }

    void ReadSlow(Controls<T> c, double now)
    {
        var x = Djay.Percent(Value(c, DjayLabels.Crossfader));
        HashSet<int> streams = [];
        foreach (var n in c.Decks)
        {
            var title = Value(c, DjayLabels.Label(DjayLabels.Title, n)) ?? "";
            var artist = Value(c, DjayLabels.Label(DjayLabels.Artist, n)) ?? "";
            Info i;
            lock (_lock) i = _info.TryGetValue(n, out var old) ? old : new Info();
            var fresh = new Info { Title = i.Title, Artist = i.Artist, File = i.File, Length = i.Length, Stream = i.Stream };
            if ((title, artist) != (i.Title, i.Artist) || (title.Length > 0 && i.File.Length == 0))
            {
                var known = title.Length == 0 ? "" : _tracks.Find(title, artist);
                var file = title.Length == 0 ? "" : _resolver.Find(known, artist, title);
                fresh.Title = title;
                fresh.Artist = artist;
                fresh.File = file;
                fresh.Length = file.Length == 0 ? 0 : Resolver.LengthOf(file) ?? 0;
                fresh.Stream = file.Length == 0 && title.Length > 0 ? _streamsKnown.Find(title, artist) : null;
                if (fresh.Stream is { } st) fresh.Length = st.Length;
            }
            if (title.Length > 0 && fresh.File.Length == 0 && fresh.Stream is null) streams.Add(n);
            fresh.Vol = Djay.Percent(Value(c, DjayLabels.Label(DjayLabels.Volume, n)));
            fresh.Bpm = c.Bpm.GetValueOrDefault(n);
            fresh.Sync = Value(c, DjayLabels.Label(DjayLabels.Sync, n)) == DjayLabels.Active;
            var tempo = Djay.Percent(Value(c, DjayLabels.Label(DjayLabels.Tempo, n))) ?? 0;
            lock (_lock)
            {
                _info[n] = fresh;
                Head(n).SetSpeed(1 + tempo, now);
            }
        }
        lock (_lock)
        {
            if (x is { } xf) _xfader = xf;
            _streamed = streams;
        }
    }

    public IReadOnlyList<DeckReading> Decks(double now)
    {
        lock (_lock)
        {
            List<DeckReading> out_ = [];
            foreach (var n in _heads.Keys.Order())
            {
                if (!_info.TryGetValue(n, out var i) || i.Title.Length == 0) continue;
                var head = _heads[n];
                var x = n % 2 == 1 ? _xfader : 1 - _xfader;  // decks 1/3 on the left of the crossfader, 2/4 on the right
                var gain = Math.Min(1, 2 * (1 - x));
                out_.Add(new DeckReading
                {
                    Deck = n, File = i.File, Pos = head.At(now), Length = i.Length, Play = head.Play, Bpm = i.Bpm,
                    Bpm0 = i.Bpm > 0 ? i.Bpm / head.Speed : 0, Vol = (i.Vol ?? 1) * gain, Received = now,
                    Title = i.Title, Artist = i.Artist, Rate = head.Play ? head.Speed : 0, Sync = i.Sync && head.Play, Stream = i.Stream,
                });
            }
            return out_;
        }
    }

    public string Summary(double now)
    {
        IReadOnlyList<int> numbers;
        lock (_lock) numbers = _controls.Decks;
        var read = Decks(now).ToDictionary(d => d.Deck);
        return string.Join("\n", numbers.Select(n => read.TryGetValue(n, out var d) ? d.Line : $"{n}: no track"));
    }
}

public static class Djay
{
    /// "01:07" → 67, "1:02:03" → 3723; anything else → nil. (No regex: it runs 200 times a second per deck.)
    public static int? Clock(string? text)
    {
        var t = (text ?? "").Trim().AsSpan();
        if (t.StartsWith("-")) t = t[1..];
        Span<Range> parts = stackalloc Range[4];
        var n = t.Split(parts, ':');
        if (n is < 2 or > 3 || t[parts[n - 1]].Length != 2) return null;
        Span<int> v = stackalloc int[3];
        for (var i = 0; i < n; i++)
        {
            var p = t[parts[i]];
            if (p.Length == 0) return null;
            foreach (var c in p) if (!char.IsAsciiDigit(c)) return null;
            if (!int.TryParse(p, NumberStyles.None, CultureInfo.InvariantCulture, out v[i])) return null;
        }
        return n == 3 ? v[0] * 3600 + v[1] * 60 + v[2] : v[0] * 60 + v[1];
    }

    /// "73%" → 0.73.
    public static double? Percent(string? text)
    {
        if (text is null) return null;
        var t = text.Trim();
        if (t.EndsWith('%')) t = t[..^1];
        return double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v / 100 : null;
    }
}

/// One deck's position from its whole-second label: a new second is seen at most `Late` after the playhead
/// crossed it, never before. Over the last ticks, the one predicting the furthest position is the least late.
public sealed class Playhead
{
    public const double Late = 0.15;  // djay redraws ~10× a second, plus our polling
    public const int Keep = 8;

    readonly List<(double Seen, double Pos)> _ticks = [];
    (double Seen, double Pos)? _coarse;
    double _frozen;

    public int? Label { get; private set; }
    public double Speed { get; private set; } = 1;
    public bool Play { get; private set; }

    public double At(double t)
    {
        var s = Play ? Speed : 0;
        if (_ticks.Count > 0) return _ticks.Max(k => k.Pos + (t - k.Seen) * s);
        if (_coarse is { } c) return c.Pos + (t - c.Seen) * s;
        return _frozen;
    }

    /// Speed or play state changes: what we know becomes one anchor at the current position.
    void Rebase(double t)
    {
        var exact = _ticks.Count > 0;
        var pos = At(t);
        _ticks.Clear();
        if (exact) { _ticks.Add((t, pos)); _coarse = null; }
        else _coarse = (t, pos);
        _frozen = pos;
    }

    public void SetPlay(bool p, double t)
    {
        if (p == Play) return;
        Rebase(t);
        Play = p;
    }

    public void SetSpeed(double s, double t)
    {
        if (Math.Abs(s - Speed) <= 1e-4) return;
        Rebase(t);
        Speed = s;
    }

    /// A new label value: a tick (the playhead crossed a whole second) or a jump (seek, loop).
    public void Seen(int value, double t)
    {
        var old = Label;
        Label = value;
        if (old is not { } o)
        {
            _coarse = (t, value + 0.5);
            _frozen = value + 0.5;
            return;
        }
        if (value == o + 1)
        {
            if (_ticks.Count > 0 && At(t) - value is var off && !(off >= -0.05 && off <= Late + 0.05)) _ticks.Clear();  // a nudge meanwhile
            _ticks.Add((t, value));
            if (_ticks.Count > Keep) _ticks.RemoveAt(0);
            _coarse = null;
            _frozen = value;
            return;
        }
        _ticks.Clear();  // anything else: the DJ moved the playhead
        _coarse = (t, value + 0.5);
        _frozen = value + 0.5;
    }
}

/// Reading djay's MediaLibrary.db (read only, never kept open: djay writes it).
static class DjayDb
{
    public static IEnumerable<byte[]> Records(string path, string collection)
    {
        if (!File.Exists(path)) yield break;
        List<byte[]> rows = [];
        try
        {
            using var db = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = SqliteOpenMode.ReadOnly, Pooling = false }.ToString());
            db.Open();
            using var cmd = db.CreateCommand();
            cmd.CommandText = "SELECT data FROM database2 WHERE collection = $c";
            cmd.Parameters.AddWithValue("$c", collection);
            using var r = cmd.ExecuteReader();
            while (r.Read()) if (!r.IsDBNull(0) && r.GetValue(0) is byte[] b) rows.Add(b);
        }
        catch (SqliteException) { }
        catch (InvalidOperationException) { }
        foreach (var b in rows) yield return b;
    }
}

/// djay's library (MediaLibrary.db, read only): a track's file by its title and artist.
public sealed class DjayLibrary(string path)
{
    readonly Lock _lock = new();
    readonly Dictionary<string, string> _files = [];  // "title\0artist" → path
    double _readAt;

    public string LibraryPath => path;

    public IReadOnlyList<string> Folders
    {
        get { lock (_lock) return [.. _files.Values.Select(f => Path.GetDirectoryName(f) ?? "").Where(d => d.Length > 0).Distinct()]; }
    }

    public string Find(string title, string artist)
    {
        var key = $"{title}\0{artist}";
        bool missing;
        lock (_lock) missing = !_files.ContainsKey(key) && Clock.Monotonic() - _readAt > 2;
        if (missing) Read();  // a track djay hasn't told us about yet: it may have just been added
        lock (_lock)
            return _files.GetValueOrDefault(key) ?? _files.FirstOrDefault(p => p.Key.StartsWith($"{title}\0", StringComparison.Ordinal)).Value ?? "";
    }

    public void Read()
    {
        Dictionary<string, string> found = [];
        foreach (var data in DjayDb.Records(path, "localMediaItemLocations"))
        {
            var s = Strings(data);
            if (s.FirstOrDefault(x => x.StartsWith("file://", StringComparison.Ordinal)) is not { } url
                || Paths.FromFileUrl(url, OperatingSystem.IsWindows()) is not { } file) continue;
            var ti = s.IndexOf("title");
            var ai = s.IndexOf("artist");
            var title = ti > 0 ? s[ti - 1] : "";
            var artist = ai > 0 ? s[ai - 1] : "";
            found[$"{title}\0{artist}"] = file;
        }
        lock (_lock)
        {
            foreach (var (k, v) in found) _files[k] = v;
            _readAt = Clock.Monotonic();
        }
    }

    /// The strings in djay's record format: 0x08, 1–1000 bytes, 0x00 (as re.findall(rb"\x08([^\x00]{1,1000})\x00")).
    public static List<string> Strings(byte[] b) => [.. DjayStreams.Scan(b, 1).Select(s => s.Text)];
}

/// The tracks djay streams (Spotify), from its library (MediaLibrary.db, read only): which recording each is (the
/// service's id, the ISRC, the length), by title and artist as its decks show them. A port of streamed.py's
/// djay_streams: djay's records are a key/value archive ("TSAF"), each value followed by its key; strings as
/// 0x08 + text + 0x00, 32-bit floats as 0x13, zero padding to a 4-byte boundary, then 4 bytes (little endian).
public sealed class DjayStreams(string path)
{
    public static readonly HashSet<string> TextKeys = ["title", "artist", "isrc"];
    public static readonly HashSet<string> Keys = [.. TextKeys, "duration", "uuid", "titleIDs", "titleID", "sourceURIs", "type", "bpm"];  // never a value

    readonly Lock _lock = new();
    Dictionary<string, StreamedTrack> _known = [];  // "title\0artist"
    double _readAt = -10;

    /// Read again (at most every 2 s) when a deck shows a track we don't know yet.
    public StreamedTrack? Find(string title, string artist)
    {
        var key = $"{title}\0{artist}";
        bool stale;
        lock (_lock) stale = !_known.ContainsKey(key) && Clock.Monotonic() - _readAt > 2;
        if (stale) Read();
        lock (_lock)
            return _known.GetValueOrDefault(key)
                ?? (title.Length > 0 ? _known.FirstOrDefault(p => p.Key.StartsWith($"{title}\0", StringComparison.Ordinal)).Value : null);
    }

    public void Read()
    {
        Dictionary<string, StreamedTrack> found = [];
        foreach (var data in DjayDb.Records(path, "globalMediaItemLocations"))
            if (Stream(data) is { } s) found[$"{s.Title}\0{s.Artist}"] = s;
        lock (_lock)
        {
            _known = found;
            _readAt = Clock.Monotonic();
        }
    }

    /// One record → its stream, nil when it isn't a streamed track.
    public static StreamedTrack? Stream(byte[] data)
    {
        var f = Fields(data);
        if (f.Uris.FirstOrDefault(u => u.StartsWith("spotify:track:", StringComparison.Ordinal)) is not { } uri
            || !f.Text.TryGetValue("title", out var title)) return null;
        return new StreamedTrack("spotify", uri.Split(':')[^1], title, f.Text.GetValueOrDefault("artist", ""),
                                 f.Text.GetValueOrDefault("isrc", ""), f.Floats.GetValueOrDefault("duration"));
    }

    /// The strings djay's records hold: 0x08, `min`–1000 bytes without a 0x00, 0x00; with where each starts and ends.
    internal static List<(int Start, int End, string Text)> Scan(byte[] b, int min)
    {
        List<(int, int, string)> out_ = [];
        var i = 0;
        while (i < b.Length)
        {
            if (b[i] == 0x08)
            {
                var limit = Math.Min(b.Length, i + 1002);
                var end = Array.IndexOf(b, (byte)0, i + 1, limit - (i + 1));
                var n = end - i - 1;
                if (end >= 0 && n >= min && n <= 1000)
                {
                    out_.Add((i, end + 1, System.Text.Encoding.UTF8.GetString(b, i + 1, n)));
                    i = end + 1;
                    continue;
                }
            }
            i++;
        }
        return out_;
    }

    /// The strings and floats of one record, by key (the first of each key: the record's own, not a nested one).
    public static (Dictionary<string, string> Text, Dictionary<string, float> Floats, List<string> Uris) Fields(byte[] b)
    {
        var strings = Scan(b, 0);  // as re.finditer(rb"\x08([^\x00]{0,1000})\x00")
        Dictionary<string, string> text = [];
        for (var i = 0; i + 1 < strings.Count; i++)
        {
            var (v, k) = (strings[i], strings[i + 1]);
            if (v.End == k.Start && TextKeys.Contains(k.Text) && !Keys.Contains(v.Text)) text.TryAdd(k.Text, v.Text);  // a value directly followed by its key
        }
        Dictionary<string, float> floats = [];
        foreach (var key in new[] { "duration", "bpm" })
        {
            byte[] needle = [0x08, .. System.Text.Encoding.UTF8.GetBytes(key), 0x00];
            var at = b.AsSpan().IndexOf(needle);
            if (at < 8) continue;
            var pad = b.AsSpan(at - 8, 4);  // the float ends where its key starts
            var last = pad.LastIndexOfAnyExcept((byte)0);
            if (last >= 0 && pad[last] == 0x13)
                floats[key] = BitConverter.Int32BitsToSingle(System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(b.AsSpan(at - 4, 4)));
        }
        var uris = strings.Select(s => s.Text).Where(u =>
        {
            var parts = u.Split(':');
            return parts.Length == 3 && parts[1] == "track" && parts[0].Length > 0 && parts[0].All(char.IsAsciiLetterLower)
                && parts[2].Length > 0 && parts[2].All(char.IsAsciiLetterOrDigit);
        }).ToList();
        return (text, floats, uris);
    }
}
