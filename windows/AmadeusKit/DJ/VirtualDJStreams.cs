// VirtualDJ's streamed tracks (Spotify) on the DJ laptop. Its plugin reports them as "netsearch://" + a two-letter
// service + the service's id ("netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"): no file to send. VirtualDJ's database.xml
// names them (<Tags Author= Title=>, <Infos SongLength=>), so Amadeus Link adds what the lighting computer needs
// to fetch a copy of the same recording itself, as for djay (a port of streamed.py's vdj_streams;
// mac/Sources/AmadeusLink/DJ/VirtualDJ.swift).
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Xml;

namespace AmadeusKit.DJ;

public sealed class VirtualDJStreams(string? path = null)
{
    public static readonly IReadOnlyDictionary<string, string> Services = new Dictionary<string, string>
    {
        ["sp"] = "spotify", ["td"] = "tidal", ["dz"] = "deezer", ["sc"] = "soundcloud", ["bp"] = "beatport", ["bs"] = "beatsource",
    };

    /// Where VirtualDJ keeps its home folder (settings, database.xml): on Windows in Documents (the Documents folder
    /// Windows knows: also when it moved into OneDrive), on some installations in %LOCALAPPDATA% or %APPDATA%;
    /// on macOS in Application Support (streamed.py vdj_homes).
    public static IReadOnlyList<string> Homes()
    {
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        if (!OperatingSystem.IsWindows())
            return [Path.Combine(home, "Library", "Application Support", "VirtualDJ"), Path.Combine(home, "Documents", "VirtualDJ")];
        List<string> homes = [Path.Combine(Paths.UserFolder(Environment.SpecialFolder.MyDocuments, "Documents"), "VirtualDJ")];
        foreach (var k in new[] { "LOCALAPPDATA", "APPDATA" })
            if (Environment.GetEnvironmentVariable(k) is { Length: > 0 } v) homes.Add(Path.Combine(v, "VirtualDJ"));
        return homes;
    }

    /// The home folder VirtualDJ really uses: the first with its settings or database in it. Documents is its
    /// default, but where Documents is on a network share (a VM's, a company's) VirtualDJ moves to %LOCALAPPDATA%.
    public static string Home()
    {
        var homes = Homes();
        return homes.FirstOrDefault(h => File.Exists(Path.Combine(h, "settings.xml")) || File.Exists(Path.Combine(h, "database.xml")))
            ?? homes.FirstOrDefault(Directory.Exists) ?? homes[0];
    }

    /// VirtualDJ's database.xml: the first home folder that has one (else where it will be).
    public static string Database()
    {
        var homes = Homes();
        return homes.Select(h => Path.Combine(h, "database.xml")).FirstOrDefault(File.Exists) ?? Path.Combine(homes[0], "database.xml");
    }

    readonly string? _fixed = path;
    Dictionary<string, StreamedTrack> _known = [];
    DateTime? _mtime;

    public string DatabasePath => _fixed ?? Database();

    /// "netsearch://sp…" → the service and its id; nil for anything else.
    public static (string Service, string Id)? Netsearch(string file)
    {
        const string prefix = "netsearch://";
        if (!file.StartsWith(prefix, StringComparison.Ordinal)) return null;
        var rest = file[prefix.Length..];
        if (rest.Length <= 2 || !rest.All(char.IsAsciiLetterOrDigit)) return null;
        var code = rest[..2];
        return (Services.GetValueOrDefault(code, code), rest[2..]);
    }

    /// The streamed track a deck reports, read again when unknown (or its length still unknown) and the database changed.
    public StreamedTrack? Find(string file)
    {
        if (Netsearch(file) is null) return null;
        if (!_known.TryGetValue(file, out var k) || k.Length == 0)
        {
            var path = DatabasePath;
            try
            {
                var m = File.GetLastWriteTimeUtc(path);
                if (File.Exists(path) && m != _mtime)
                {
                    _mtime = m;
                    if (Files.ReadBytes(path) is { } data) _known = Parse(data);
                }
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
        return _known.GetValueOrDefault(file);
    }

    public static Dictionary<string, StreamedTrack> Parse(byte[] data)
    {
        Dictionary<string, StreamedTrack> found = [];
        string? file = null;
        string title = "", artist = "";
        double length = 0;
        try
        {
            using var r = XmlReader.Create(new MemoryStream(data), new XmlReaderSettings { DtdProcessing = DtdProcessing.Ignore, XmlResolver = null });
            void End()
            {
                if (file is not null && title.Length > 0 && Netsearch(file) is { } ns)
                    found[file] = new StreamedTrack(ns.Service, ns.Id, title, artist, Length: length);
                file = null;
            }
            while (r.Read())
            {
                if (r.NodeType == XmlNodeType.Element)
                {
                    var empty = r.IsEmptyElement;
                    switch (r.Name)
                    {
                        case "Song":
                            var fp = r.GetAttribute("FilePath") ?? "";
                            file = Netsearch(fp) is not null ? fp : null;
                            title = ""; artist = ""; length = 0;
                            if (empty) End();
                            break;
                        case "Tags" when file is not null:
                            title = r.GetAttribute("Title") ?? "";
                            artist = r.GetAttribute("Author") ?? "";
                            break;
                        case "Infos" when file is not null:
                            length = Length(r.GetAttribute("SongLength"));
                            break;
                    }
                }
                else if (r.NodeType == XmlNodeType.EndElement && r.Name == "Song") End();
            }
        }
        catch (XmlException) { }  // what was read before the damage is kept
        return found;
    }

    /// A length from the database: a whole number of seconds is VirtualDJ's guess before it has the stream (unknown).
    public static double Length(string? text) =>
        double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var l) && l != Math.Round(l) ? l : 0;

    /// A plugin packet with its streamed decks named: "file" "" (nothing to fetch from this laptop), the title, the
    /// artist and "stream" (the lighting computer fetches a copy). Unchanged when no deck streams.
    public byte[] Enrich(byte[] packet)
    {
        if (packet.AsSpan().IndexOf("netsearch://"u8) < 0) return packet;
        JsonNode? root;
        try { root = JsonNode.Parse(packet); }
        catch (JsonException) { return packet; }
        if (root is not JsonObject obj || obj["decks"] is not JsonArray decks) return packet;
        foreach (var d in decks.OfType<JsonObject>())
        {
            if (d["file"] is not JsonValue fv || !fv.TryGetValue<string>(out var file) || Netsearch(file) is not { } ns) continue;
            d["file"] = "";
            if (Find(file) is not { } s) continue;  // not named yet: listed, dark
            d["title"] = s.Title;
            d["artist"] = s.Artist;
            if (s.Length > 0) d["len"] = s.Length;
            d["stream"] = new JsonObject { ["service"] = ns.Service, ["id"] = ns.Id, ["isrc"] = "" };
        }
        return Encoding.UTF8.GetBytes(obj.ToJsonString());
    }
}
