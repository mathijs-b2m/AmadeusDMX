// Amadeus Link's djay Pro and Mixxx readers against the engine's own (amadeus/show/sources/djay.py, mixxx.py,
// winmidi.py and streamed.py): the expected values are what the Python code gives for the same input. The first
// tests are mac/Tests/AmadeusLinkTests/ReadersTests.swift, test for test.
using System.Text;
using System.Text.Json;
using AmadeusKit.DJ;
using Microsoft.Data.Sqlite;

namespace AmadeusKit.Tests;

public class ReadersTests
{
    static bool Near(double a, double b, double eps = 1e-9) => Math.Abs(a - b) < eps;

    [Fact]
    public void PlayheadFollowsWholeSecondTicks()
    {
        var h = new Playhead();
        h.SetPlay(true, 0);
        h.Seen(10, 0);
        Assert.True(Near(h.At(0), 10.5) && Near(h.At(0.5), 11.0));  // the first label: ± half a second
        h.Seen(11, 0.55);
        Assert.True(Near(h.At(0.55), 11.0) && Near(h.At(1.0), 11.45));  // a tick: exact, at most 150 ms late
        h.Seen(12, 1.53);
        Assert.True(Near(h.At(1.53), 12.0) && Near(h.At(2.0), 12.47));  // the least late tick wins
        h.SetSpeed(1.05, 2.0);
        Assert.True(Near(h.At(2.0), 12.47) && Near(h.At(3.0), 13.52));
        h.Seen(40, 3.1);
        Assert.True(Near(h.At(3.1), 40.5) && Near(h.At(3.6), 41.025));  // a jump: half a second uncertain again
        h.SetPlay(false, 4.0);
        Assert.True(Near(h.At(4.0), 41.445) && Near(h.At(9.0), 41.445));  // paused: stands still
    }

    [Fact]
    public void DjayLabels_()
    {
        Assert.Equal([67, 3723, 5, null, null], new[] { "01:07", "1:02:03", "-0:05", "x", "7" }.Select(Djay.Clock));
        Assert.Equal(0.73, Djay.Percent("73%"));
        Assert.Equal(1.0, Djay.Percent(" 100 "));
        Assert.Null(Djay.Percent("x"));
        Assert.Null(Djay.Clock("1:2"));
        Assert.Null(Djay.Clock("١:٠٢"));  // digits, but not ASCII ones
    }

    [Fact]
    public void UiaValuesReadAsOnMacOS()
    {
        // djay.py uia_text
        Assert.Equal("01:07", DjayLabels.UiaText("01:07", 1));
        Assert.Equal("Active", DjayLabels.UiaText(toggle: 1));
        Assert.Equal("Inactive", DjayLabels.UiaText(toggle: 0));
        Assert.Equal("-2.5%", DjayLabels.UiaText(range: (-2.5, -8, 8), label: "Tempo, Deck 1"));
        Assert.Equal("75%", DjayLabels.UiaText(range: (0.75, 0, 1), label: "Line volume, Deck 1"));
        Assert.Equal("33.3333%", DjayLabels.UiaText(range: (1, 0, 3), label: "Crossfader"));
        Assert.Null(DjayLabels.UiaText(range: (1, 1, 1), label: "Crossfader"));
        Assert.Null(DjayLabels.UiaText());
        Assert.True(DjayLabels.Wanted("Crossfader") && DjayLabels.Wanted("125.0, Deck 2") && !DjayLabels.Wanted("Library"));
    }

    [Fact]
    public void ControlsSayTheirDecksAndTempo()
    {
        var c = new Controls<int>(new() { ["Elapsed time, Deck 2"] = [1], ["Elapsed time, Deck 1"] = [2], ["125.0, Deck 1"] = [3],
                                         ["Title, Deck 3"] = [4], ["Crossfader"] = [5] });
        Assert.Equal([1, 2], c.Decks);
        Assert.Equal(125.0, c.Bpm[1]);
        Assert.False(c.Bpm.ContainsKey(2));
    }

    [Fact]
    public void DjayLibraryRecordStrings()
    {
        var blob = Encoding.UTF8.GetBytes("junk\u0008file:///Users/x/Music/A%20B.mp3\0\u0008Song\0\u0008title\0\u0008Art\0\u0008artist\0\u0008")
            .Concat(Enumerable.Repeat((byte)'z', 1001)).Concat(Encoding.UTF8.GetBytes("\0tail")).ToArray();
        Assert.Equal(["file:///Users/x/Music/A%20B.mp3", "Song", "title", "Art", "artist"], DjayLibrary.Strings(blob));
    }

    [Fact]
    public void FileUrlsBecomePaths()
    {
        // system.py file_url_path
        Assert.Equal("/Users/me/a b.mp3", Paths.FromFileUrl("file:///Users/me/a%20b.mp3", windows: false));
        Assert.Equal(@"C:\Music\a b.mp3", Paths.FromFileUrl("file:///C:/Music/a%20b.mp3", windows: true));
        Assert.Equal(@"C:\Music\a.mp3", Paths.FromFileUrl("file:///C|/Music/a.mp3", windows: true));
        Assert.Equal(@"\\server\share\a.mp3", Paths.FromFileUrl("file://server/share/a.mp3", windows: true));
        Assert.Null(Paths.FromFileUrl("https://x/a.mp3", windows: true));
        Assert.Equal("a.mp3", Paths.LastComponent(@"C:\Music\a.mp3"));
    }

    [Fact]
    public void TitleWords() =>
        Assert.Equal(["cafe", "del", "mar", "energy", "52", "original", "mix"], Resolver.Words("Café del Mar – Energy 52 (Original_Mix)"));

    static readonly byte[] DeckMessage = [240, 125, 68, 76, 1, 1, 2, 15, 4, 0, 4, 12, 51, 0, 8, 74, 81, 0, 2, 88, 68, 64, 62, 71, 104, 0, 7, 92,
                                          36, 102, 50, 0, 77, 247];

    [Fact]
    public void MixxxDeckMessage()
    {
        var m = MixxxReader.Decode(DeckMessage)!;
        Assert.True(m["deck"] == 2 && m["play"] == 1 && m["loop"] == 1 && m["orientation"] == 1);
        Assert.True(Near(m["pos"], 67.123) && m["samples"] == 18_000_000 && m["rate"] == 44100);
        Assert.True(Near(m["ratio"], 1.025) && Near(m["bpm"], 126.5) && Near(m["vol"], 0.7999755844472929));
        Assert.Equal(77, m["seq"]);
    }

    [Fact]
    public void MixxxCrossfader()
    {
        var m = MixxxReader.Decode([240, 125, 68, 76, 1, 2, 32, 0, 247])!;
        Assert.True(Near(m["xfader"], -0.49996948055911616));
        Assert.True(Near(MixxxReader.XfadeGain(0.6, 0), 0.4) && MixxxReader.XfadeGain(0.6, 2) == 1 && MixxxReader.XfadeGain(-0.3, 0) == 1);
        Assert.Null(MixxxReader.Decode([1, 2, 3]));
    }

    [Fact]
    public void SysExAcrossWinMMBuffers()
    {
        var s = new SysExAssembler();
        Assert.Empty(s.Feed(DeckMessage.AsSpan(0, 10)));
        var got = s.Feed([.. DeckMessage.AsSpan(10), 0x90, 0xF0, 1, 0xF7]);
        Assert.Equal(2, got.Count);
        Assert.Equal(DeckMessage, got[0]);
        Assert.Equal([0xF0, 1, 0xF7], got[1]);
        Assert.Empty(s.Feed([5, 0xF7]));  // the tail of a message we never saw start
    }

    [Fact]
    public void MidiPortsByName()
    {
        // winmidi.py matching
        Assert.Equal(1, MidiPorts.Matching(["Amadeus DMX 2", "Amadeus DMX", "x"], "Amadeus DMX"));
        Assert.Equal(0, MidiPorts.Matching(["Amadeus DMX group 1", "y"], "Amadeus DMX"));
        Assert.Equal(1, MidiPorts.Matching(["Bus 2", "IAC Driver Bus 1"], "Bus 1"));
        Assert.Null(MidiPorts.Matching(["Amadeus DMX 1"], "Amadeus DMX", loose: false));
        Assert.Null(MidiPorts.Matching(["loopMIDI Port"], "Amadeus DMX"));
    }

    [Fact]
    public void PacketLeavesOutDecksWithoutAFile()
    {
        DeckReading[] decks =
        [
            new() { Deck = 1, File = "/a.mp3", Pos = 10, Length = 200, Play = true, Bpm = 125, Bpm0 = 125, Vol = 1, Received = 5, Sync = true },
            new() { Deck = 2, File = "", Received = 5, Title = "Spotify" },
        ];
        var o = J.ParseElement(Packet.Make("djay Pro", decks, 5.5, 5));
        var list = o.GetProperty("decks");
        Assert.True(o.GetProperty("app").GetString() == "djay Pro" && o.GetProperty("t").GetInt32() == 500 && list.GetArrayLength() == 1);
        Assert.True(list[0].GetProperty("pos").GetDouble() == 10.5 && list[0].GetProperty("sync").GetInt32() == 1);
    }

    // djay's library records, built as tests/test_streamed.py builds them
    static byte[] S8(string text) => [0x08, .. Encoding.UTF8.GetBytes(text), 0x00];

    static List<byte> F32(List<byte> d, float value)
    {
        d.Add(0x13);
        d.AddRange(new byte[(4 - d.Count % 4) % 4]);
        d.AddRange(BitConverter.GetBytes(value));
        return d;
    }

    static byte[] Location(string title, string artist, string uri, string isrc, float length)
    {
        List<byte> d = [.. "TSAF"u8, 3, 0, 3, 0, .. S8("ADCMediaItemLocation"), .. S8("ab12"), .. S8("uuid"), 5, 2];
        d.AddRange([.. S8(title), .. S8("title"), .. S8(artist), .. S8("artist")]);
        d = F32(d, length);
        d.AddRange([.. S8("duration"), .. S8(isrc), .. S8("isrc"), .. S8(uri), .. S8("sourceURIs")]);
        return [.. d];
    }

    [Fact]
    public void DjayStreamedRecord()
    {
        var s = DjayStreams.Stream(Location("Toxic", "Britney Spears", "spotify:track:6I9VzX", "USJI10301102", 198.8f))!;
        Assert.True(s.Service == "spotify" && s.Id == "6I9VzX" && s.Isrc == "USJI10301102");
        Assert.True(s.Title == "Toxic" && s.Artist == "Britney Spears" && Math.Abs(s.Length - 198.8) < 1e-3);
        Assert.Null(DjayStreams.Stream([.. S8("file:///x.mp3"), .. S8("Local"), .. S8("title")]));  // a file: not streamed
    }

    [Fact]
    public void DjayMissingArtistIsNotAKey()
    {
        var f = DjayStreams.Fields([.. S8("Zebra"), .. S8("title"), .. S8("artist"), .. S8("spotify:track:x"), .. S8("sourceURIs")]);
        Assert.True(f.Text["title"] == "Zebra" && !f.Text.ContainsKey("artist"));
        Assert.Equal(["spotify:track:x"], f.Uris);
    }

    [Fact]
    public void PacketCarriesAStreamedDeck()
    {
        var st = new StreamedTrack("spotify", "6I9", "Toxic", "Britney Spears", "US1", 198.8);
        var d = new DeckReading { Deck = 2, File = "", Pos = 30, Length = 198.8, Play = true, Bpm = 143, Bpm0 = 143, Vol = 1, Received = 1,
                                  Title = "Toxic", Artist = "Britney Spears", Stream = st };
        var deck = J.ParseElement(Packet.Make("djay Pro", [d], 1, 0)).GetProperty("decks")[0];
        Assert.True(deck.GetProperty("file").GetString() == "" && deck.GetProperty("title").GetString() == "Toxic");
        Assert.Equal("""{"service":"spotify","id":"6I9","isrc":"US1"}""", deck.GetProperty("stream").GetRawText());
    }

    const string VdjDatabase = """
        <?xml version="1.0" encoding="UTF-8"?>
        <VirtualDJ_Database Version="2025">
         <Song FilePath="netsearch://sp1fI4E7jeOiyfa3LmwNnD0o" Flag="256">
          <Tags Author="Paul Kalkbrenner" Title="DIE TROMPETEN VON BERLIN" Album="THE ESSENCE" Year="2025" />
          <Infos SongLength="330.022109" Bitrate="320" />
         </Song>
         <Song FilePath="netsearch://sp4eE4vEaakr3ZnSt1UNfOhz" Flag="256">
          <Tags Author="Emrod" Title="Tango" />
          <Infos SongLength="240.0" />
         </Song>
         <Song FilePath="/Music/local.mp3"><Tags Author="A" Title="Local" /><Infos SongLength="200.5" /></Song>
        </VirtualDJ_Database>
        """;

    [Fact]
    public void VirtualDJDatabase()
    {
        var found = VirtualDJStreams.Parse(Encoding.UTF8.GetBytes(VdjDatabase));
        Assert.Equal(2, found.Count);
        var s = found["netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"];
        Assert.True(s.Service == "spotify" && s.Id == "1fI4E7jeOiyfa3LmwNnD0o" && s.Artist == "Paul Kalkbrenner");
        Assert.True(s.Title == "DIE TROMPETEN VON BERLIN" && Math.Abs(s.Length - 330.022109) < 1e-6);
        Assert.Equal(0, found["netsearch://sp4eE4vEaakr3ZnSt1UNfOhz"].Length);  // 240.0: VirtualDJ's guess, unknown
        Assert.Null(VirtualDJStreams.Netsearch("/Music/local.mp3"));
    }

    [Fact]
    public void VirtualDJPacketNamesItsStreams()
    {
        using var w = new TempWorkspace();
        w.Write("database.xml", VdjDatabase);
        var path = Path.Combine(w.Root, "database.xml");
        var packet = Encoding.UTF8.GetBytes("""
            {"t":1,"master":2,"decks":[{"deck":1,"pos":0,"len":240,"play":0,"bpm":125,"bpm0":124,"vol":1,"file":"/Music/local.mp3"},{"deck":2,"pos":34.4,"len":330,"play":1,"bpm":125.4,"bpm0":137.4,"vol":1,"file":"netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"}]}
            """);
        var decks = J.ParseElement(new VirtualDJStreams(path).Enrich(packet)).GetProperty("decks");
        Assert.True(decks[0].GetProperty("file").GetString() == "/Music/local.mp3" && !decks[0].TryGetProperty("stream", out _));  // a file: as it was
        Assert.True(decks[1].GetProperty("file").GetString() == "" && decks[1].GetProperty("title").GetString() == "DIE TROMPETEN VON BERLIN");
        Assert.True(decks[1].GetProperty("artist").GetString() == "Paul Kalkbrenner" && Math.Abs(decks[1].GetProperty("len").GetDouble() - 330.022109) < 1e-6);
        Assert.Equal("""{"service":"spotify","id":"1fI4E7jeOiyfa3LmwNnD0o","isrc":""}""", decks[1].GetProperty("stream").GetRawText());
        var plain = """{"decks":[{"deck":1,"file":"/x.mp3"}]}"""u8.ToArray();
        Assert.Same(plain, new VirtualDJStreams(path).Enrich(plain));  // nothing streams: untouched
    }

    // MARK: the readers end to end (beyond the Mac's tests): what they read becomes the plugin's packet

    sealed class FakeWindow : IDjayWindow<string>
    {
        public readonly Dictionary<string, string> Values = [];
        public void Attach() { }
        public Dictionary<string, List<string>> Scan() { lock (Values) return Values.Keys.Where(DjayLabels.Wanted).ToDictionary(k => k, k => new List<string> { k }); }
        public string? Read(string control) { lock (Values) return Values.GetValueOrDefault(control); }
        public string Note => "";
        public void Set(string k, string v) { lock (Values) Values[k] = v; }
    }

    static void Library(string db, string collection, params byte[][] records)
    {
        using var c = new SqliteConnection($"Data Source={db};Pooling=False");
        c.Open();
        using var create = c.CreateCommand();
        create.CommandText = "CREATE TABLE IF NOT EXISTS database2 (collection TEXT, key TEXT, data BLOB)";
        create.ExecuteNonQuery();
        foreach (var r in records)
        {
            using var ins = c.CreateCommand();
            ins.CommandText = "INSERT INTO database2 VALUES ($c, 'k', $d)";
            ins.Parameters.AddWithValue("$c", collection);
            ins.Parameters.AddWithValue("$d", r);
            ins.ExecuteNonQuery();
        }
    }

    [Fact]
    public async Task DjaysWindowBecomesThePluginsPacket()
    {
        using var w = new TempWorkspace();
        w.Write("Music/Daft Punk - One More Time.mp3", "audio");
        var file = Path.Combine(w.Root, "Music", "Daft Punk - One More Time.mp3");
        var db = Path.Combine(w.Root, "MediaLibrary.db");
        Library(db, "localMediaItemLocations",
                [.. S8(new Uri(file).AbsoluteUri), .. S8("One More Time"), .. S8("title"), .. S8("Daft Punk"), .. S8("artist")]);
        Library(db, "globalMediaItemLocations", Location("Toxic", "Britney Spears", "spotify:track:6I9VzX", "USJI10301102", 198.8f));

        var win = new FakeWindow();
        void Deck(int n, string title, string artist, string elapsed, bool play, string tempo, string volume, bool sync = false)
        {
            win.Set($"Title, Deck {n}", title);
            win.Set($"Artist, Deck {n}", artist);
            win.Set($"Elapsed time, Deck {n}", elapsed);
            win.Set($"Play / Pause, Deck {n}", play ? "Active" : "Inactive");
            win.Set($"Tempo, Deck {n}", tempo);
            win.Set($"Line volume, Deck {n}", volume);
            win.Set($"Sync, Deck {n}", sync ? "Active" : "Inactive");
        }
        Deck(1, "One More Time", "Daft Punk", "01:06", true, "2%", "80%", sync: true);
        Deck(2, "Toxic", "Britney Spears", "00:30", false, "0%", "100%");
        Deck(3, "Unknown", "Nobody", "00:10", false, "0%", "100%");
        win.Set("125.0, Deck 1", "");
        win.Set("Crossfader", "50%");

        var reader = new DjayReader<string>(win, db, new Resolver([Path.Combine(w.Root, "Music")]));
        try
        {
            var start = Clock.Monotonic();
            IReadOnlyList<DeckReading> decks = [];
            for (var i = 0; i < 100 && (decks.Count < 3 || decks[0].File.Length == 0); i++)
            {
                await Task.Delay(50);
                decks = reader.Decks(Clock.Monotonic());
            }
            win.Set("Elapsed time, Deck 1", "01:07");  // a tick: the playhead crossed 67 s just now
            await Task.Delay(100);
            var now = Clock.Monotonic();
            decks = reader.Decks(now);
            Assert.Equal(3, decks.Count);
            var one = decks[0];
            Assert.Equal(file, one.File);
            Assert.True(one.Play && one.Sync && Near(one.Rate, 1.02) && one.Bpm == 125.0 && Near(one.Bpm0, 125 / 1.02));
            Assert.InRange(one.Pos, 67.0, 67.0 + 0.3);
            Assert.Equal(0.8, one.Vol, 6);  // centre crossfader: full gain
            Assert.Equal("6I9VzX", decks[1].Stream?.Id);
            Assert.True(decks[2].File.Length == 0 && decks[2].Stream is null);
            Assert.Contains("neither a file here nor a stream", reader.Note);
            Assert.Contains("3: ■ Nobody – Unknown  (no file on this laptop: not sent)", reader.Summary(now));

            var packet = J.ParseElement(Packet.Make(reader.App, decks, now, start));
            var list = packet.GetProperty("decks");
            Assert.Equal(2, list.GetArrayLength());  // deck 3 can't be lit: left out
            Assert.Equal(file, list[0].GetProperty("file").GetString());
            Assert.Equal(1, list[0].GetProperty("sync").GetInt32());
            Assert.Equal("spotify", list[1].GetProperty("stream").GetProperty("service").GetString());
            Assert.Equal(198.8, list[1].GetProperty("len").GetDouble(), 3);
        }
        finally { reader.Stop(); }
    }

    [Fact]
    public void MixxxMessagesBecomeDecks()
    {
        using var w = new TempWorkspace();
        w.Write("Music/track.mp3", "audio");
        var file = Path.Combine(w.Root, "Music", "track.mp3");
        var settings = Path.Combine(w.Root, "Mixxx");
        Directory.CreateDirectory(settings);
        var Len = (18_000_000 / 2.0 / 44100).ToString(System.Globalization.CultureInfo.InvariantCulture);
        using (var c = new SqliteConnection($"Data Source={Path.Combine(settings, "mixxxdb.sqlite")};Pooling=False"))
        {
            c.Open();
            using var cmd = c.CreateCommand();
            cmd.CommandText = $"""
                CREATE TABLE library (id INTEGER, artist TEXT, title TEXT, bpm REAL, samplerate INTEGER, duration REAL, location INTEGER, mixxx_deleted INTEGER);
                CREATE TABLE track_locations (id INTEGER, location TEXT);
                INSERT INTO track_locations VALUES (1, '{file}'), (2, '/elsewhere/other.mp3');
                INSERT INTO library VALUES (1, 'Artist', 'Title', 126.4, 44100, {Len}, 1, 0);
                INSERT INTO library VALUES (2, 'Other', 'Same length', 90, 44100, {Len}, 2, 0);
                """;
            cmd.ExecuteNonQuery();
        }
        w.Write("mapping/Amadeus-DMX.midi.xml", "<x/>");
        w.Write("mapping/README.txt", "not copied");
        Action<byte[]>? feed = null;
        var r = new MixxxReader(f => { feed = f; return (new Disposable(), "Amadeus DMX"); }, Path.Combine(w.Root, "mapping"), settings,
                                new Resolver([Path.Combine(w.Root, "Music")]));
        Assert.True(File.Exists(Path.Combine(settings, "controllers", "Amadeus-DMX.midi.xml")));
        Assert.False(File.Exists(Path.Combine(settings, "controllers", "README.txt")));
        Assert.StartsWith("In Mixxx: Preferences › Controllers", r.Note);
        r.Message(DeckMessage, 10.0);
        Assert.Empty(r.Decks(10.1));  // a track just loaded: its position means nothing yet
        r.Message(DeckMessage, 10.5);
        r.Message([240, 125, 68, 76, 1, 2, 32, 0, 247], 10.5);  // the crossfader half-way left: deck 2 sits in the centre
        var d = Assert.Single(r.Decks(10.6));
        Assert.True(d.Deck == 2 && d.File == file && d.Title == "Title" && d.Artist == "Artist" && d.Id == "18000000@44100");
        Assert.True(Near(d.Length, 18_000_000 / 2.0 / 44100) && Near(d.Rate, 1.025) && Near(d.Bpm0, 126.5 / 1.025));
        Assert.True(Near(d.Vol, 0.7999755844472929) && d.Play);
        Assert.Equal("", r.Note);
        Assert.Empty(r.Decks(12.0));  // nothing from Mixxx for a second: unloaded
        Assert.NotNull(feed);
        var none = new MixxxReader(_ => throw new MidiPortException("no port"), settings: settings);
        Assert.Equal("no port", none.Note);
    }

    sealed class Disposable : IDisposable { public void Dispose() { } }
}
