// Which file on this laptop a DJ software's track is (as amadeus/show/sources/resolve.py): the path as given,
// then a file of that name, then a file whose name holds the title and the artist, its length deciding between
// look-alikes. Looks in the Music folder and in the folders the DJ software's library knows.
// (mac/Sources/AmadeusLink/DJ/Resolver.swift)
using System.Globalization;
using System.Text;

namespace AmadeusKit.DJ;

public sealed class Resolver
{
    public static readonly HashSet<string> Audio = ["mp3", "wav", "flac", "aiff", "aif", "m4a", "aac", "ogg", "opus", "alac"];
    public const double LengthTolerance = 2.5;

    /// A track's length in seconds, nil when unknown. The app gives the system's (Windows: the file's
    /// System.Media.Duration property); none here, so the kit stays free of Windows APIs.
    public static Func<string, double?> LengthOf { get; set; } = _ => null;

    readonly Lock _lock = new();
    readonly List<string> _folders = [];
    List<string> _files = [];
    Dictionary<string, List<string>> _byName = [];
    Dictionary<string, string> _memo = [];
    Task _indexing = Task.CompletedTask;

    public Resolver(IEnumerable<string>? folders = null) =>
        Add(folders ?? [Paths.UserFolder(Environment.SpecialFolder.MyMusic, "Music")]);

    /// Done indexing what was added so far (tests).
    public Task Indexed { get { lock (_lock) return _indexing; } }

    static string Norm(string p) => Path.TrimEndingDirectorySeparator(Path.GetFullPath(p));

    static bool Inside(string f, string root) =>
        f.Equals(root, StringComparison.OrdinalIgnoreCase)
        || f.StartsWith(root + Path.DirectorySeparatorChar, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);

    /// More places to look (where the DJ software's known tracks are), indexed in the background.
    public void Add(IEnumerable<string> more)
    {
        List<string> fresh = [];
        lock (_lock)
        {
            foreach (var f in more.Where(m => m.Length > 0).Select(Norm).Distinct())
            {
                if (_folders.Concat(fresh).Any(r => Inside(f, r))) continue;
                fresh = [.. fresh.Where(n => !Inside(n, f)), f];
            }
            _folders.AddRange(fresh);
            if (fresh.Count == 0) return;
            var before = _indexing;
            _indexing = Task.Run(async () => { await before; Index(fresh); });
        }
    }

    void Index(List<string> roots)
    {
        List<string> found = [];
        var options = new EnumerationOptions { RecurseSubdirectories = true, IgnoreInaccessible = true, AttributesToSkip = FileAttributes.Hidden | FileAttributes.System };
        foreach (var root in roots)
        {
            try
            {
                found.AddRange(Directory.EnumerateFiles(root, "*", options)
                    .Where(f => Audio.Contains(Path.GetExtension(f).TrimStart('.').ToLowerInvariant()) && !Path.GetFileName(f).StartsWith('.')));
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
        lock (_lock)
        {
            var byName = _byName.ToDictionary(p => p.Key, p => new List<string>(p.Value));
            foreach (var f in found)
            {
                var k = Path.GetFileName(f).ToLowerInvariant();
                if (!byName.TryGetValue(k, out var l)) byName[k] = l = [];
                l.Add(f);
            }
            _files = [.. _files, .. found];  // whole lists: a reader never sees half
            _byName = byName;
            _memo = _memo.Where(p => p.Value.Length > 0).ToDictionary();  // what wasn't found may be there now
        }
    }

    /// The local file, or "" (unknown, or not indexed yet).
    public string Find(string path = "", string artist = "", string title = "", double length = 0)
    {
        var key = $"{path}|{artist}|{title}|{(long)Math.Round(length, MidpointRounding.AwayFromZero)}";
        lock (_lock) if (_memo.TryGetValue(key, out var hit)) return hit;
        if (path.Length > 0 && File.Exists(path)) return Remember(key, path);
        List<string> all;
        Dictionary<string, List<string>> names;
        lock (_lock) (names, all) = (_byName, _files);
        var name = path.Length == 0 ? "" : Paths.LastComponent(path).ToLowerInvariant();
        if (names.TryGetValue(name, out var same) && same.Count > 0) return Remember(key, Closest(same, length));
        var wantTitle = Words(title).ToHashSet();
        var wantArtist = Words(artist).ToHashSet();
        if (wantTitle.Count == 0) return Remember(key, "");
        var hits = all.Select(f =>
        {
            var have = Words(Path.GetFileNameWithoutExtension(f)).Concat(Words(Path.GetFileName(Path.GetDirectoryName(f) ?? ""))).ToHashSet();
            return wantTitle.IsSubsetOf(have) ? (Score: wantArtist.Intersect(have).Count(), File: f) : (Score: -1, File: f);
        }).Where(h => h.Score >= 0).ToList();
        if (hits.Count == 0) return Remember(key, "");
        var best = hits.Max(h => h.Score);
        return Remember(key, Closest([.. hits.Where(h => h.Score == best).Select(h => h.File)], length));
    }

    string Remember(string key, string path)
    {
        lock (_lock) _memo[key] = path;
        return path;
    }

    static string Closest(List<string> files, double length)
    {
        if (files.Count <= 1 || length <= 0) return files[0];
        var best = files.Select(f => (D: Math.Abs((LengthOf(f) ?? 0) - length), F: f)).MinBy(x => x.D);
        return best.D < LengthTolerance ? best.F : files[0];
    }

    /// Lower-case words without accents: "Café del Mar" → ["cafe", "del", "mar"].
    public static List<string> Words(string s)
    {
        var plain = new StringBuilder();
        foreach (var c in s.Normalize(NormalizationForm.FormKD))
            if (c < 128) plain.Append(char.ToLowerInvariant(c));
            else if (CharUnicodeInfo.GetUnicodeCategory(c) != UnicodeCategory.NonSpacingMark) plain.Append(' ');
        return [.. plain.ToString().Split(c => !char.IsAsciiLetterOrDigit(c))];
    }
}

static class SplitExtension
{
    public static string[] Split(this string s, Func<char, bool> separator)
    {
        List<string> parts = [];
        var start = -1;
        for (var i = 0; i <= s.Length; i++)
        {
            var sep = i == s.Length || separator(s[i]);
            if (!sep && start < 0) start = i;
            else if (sep && start >= 0) { parts.Add(s[start..i]); start = -1; }
        }
        return [.. parts];
    }
}
