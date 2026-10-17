// The app's own settings (UserDefaults on the Mac): a small JSON file in the data folder, read once and saved on
// every change. Like UserDefaults, the command line overrides it for one run: `AmadeusDMX.exe -section rig
// -startLive YES` (the argument domain, for testing and screenshots); those values are never saved.
using System.Globalization;

namespace AmadeusKit;

public sealed class Defaults
{
    /// The app's settings. The app sets it at startup (`Defaults.Standard = new Defaults(path, args)`); until
    /// then (and in tests) settings live in memory only.
    public static Defaults Standard { get; set; } = new(null, []);

    readonly string? _file;
    readonly Dictionary<string, JSONValue> _values;
    readonly Dictionary<string, string> _arguments;
    readonly Lock _lock = new();

    /// `file`: where to keep them (nil: in memory). `args`: the command line, `-key value` pairs.
    public Defaults(string? file, IReadOnlyList<string> args)
    {
        _file = file;
        _values = file is not null && File.Exists(file) ? Read(file) : [];
        _arguments = Arguments(args);
    }

    /// `%LOCALAPPDATA%\<folder>\settings.json` (the folder of the app's data: "Amadeus DMX", "Amadeus Link").
    public static string FileFor(string folder) =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), folder, "settings.json");

    static Dictionary<string, JSONValue> Read(string file)
    {
        try { return JSONValue.ParseObject(File.ReadAllBytes(file)) ?? []; }
        catch (IOException) { return []; }
    }

    static Dictionary<string, string> Arguments(IReadOnlyList<string> args)
    {
        var d = new Dictionary<string, string>();
        for (var i = 0; i + 1 < args.Count; i++)
            if (args[i].Length > 1 && args[i][0] == '-' && !char.IsDigit(args[i][1]))
            {
                d[args[i][1..]] = args[i + 1];
                i++;
            }
        return d;
    }

    // MARK: reading

    /// The value (the command line first), nil when not set.
    public JSONValue? Object(string key)
    {
        lock (_lock)
        {
            if (_arguments.TryGetValue(key, out var a)) return a;
            return _values.GetValueOrDefault(key);
        }
    }

    public string? String(string key) => Object(key) switch
    {
        { String: { } s } => s,
        { Number: { } n } => n.ToString(CultureInfo.InvariantCulture),
        { Bool: { } b } => b ? "YES" : "NO",
        _ => null,
    };

    /// false when not set; "YES", "true" and "1" are true (as UserDefaults reads the command line).
    public bool Bool(string key) => Object(key) switch
    {
        { Bool: { } b } => b,
        { Number: { } n } => n != 0,
        { String: { } s } => s.Equals("yes", StringComparison.OrdinalIgnoreCase) || s.Equals("true", StringComparison.OrdinalIgnoreCase)
                             || (double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var n) && n != 0),
        _ => false,
    };

    /// nil when not set (Swift: `object(forKey:) as? Bool`).
    public bool? BoolIfSet(string key) => Object(key) is null ? null : Bool(key);

    /// 0 when not set.
    public double Double(string key) => Object(key) switch
    {
        { Number: { } n } => n,
        { Bool: { } b } => b ? 1 : 0,
        { String: { } s } when double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var n) => n,
        _ => 0,
    };

    public int Integer(string key) => (int)Math.Truncate(Double(key));

    public bool Contains(string key) => Object(key) is not null;

    // MARK: writing

    public void Set(string key, JSONValue? value)
    {
        lock (_lock)
        {
            if (value is null || value.IsNull) _values.Remove(key);
            else _values[key] = value;
            Save();
        }
    }

    public void Set(string key, string? value) => Set(key, value is null ? null : JSONValue.Of(value));
    public void Set(string key, bool value) => Set(key, JSONValue.Of(value));
    public void Set(string key, double value) => Set(key, JSONValue.Of(value));
    public void Remove(string key) => Set(key, (JSONValue?)null);

    void Save()
    {
        if (_file is null) return;
        try { Files.WriteAtomic(_file, JSONValue.ToJson(_values, pretty: true, sortKeys: true)); }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }
}

static class Files
{
    /// Writes a whole file at once (a reader never sees half of it), making its folder if needed.
    public static void WriteAtomic(string path, byte[] data)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, data);
        File.Move(tmp, path, overwrite: true);
    }

    public static string? ReadText(string path)
    {
        try { return File.ReadAllText(path); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }

    public static byte[]? ReadBytes(string path)
    {
        try { return File.ReadAllBytes(path); }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException) { return null; }
    }
}
