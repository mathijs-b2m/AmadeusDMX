// The words the apps show, in the user's language. The English text is the key: `L("Settings")` gives the
// translation from Strings/<language>.json (embedded), or the English when there is none, so a page that isn't
// translated yet still works and a changed English wording falls back to English until it is translated again
// (StringsTests lists what is missing). A sentence with values is one string with numbered holes, never pieces:
// `L("{0} m tall", h)`, so a translation can put the words in its own order.
//
// Only what is shown: numbers in files, on the command line and on the wire stay InvariantCulture (PORTING.md),
// which is why the app never sets CurrentCulture and formats the holes here, with `Strings.Culture`.
using System.Globalization;

namespace AmadeusKit;

public static class Strings
{
    /// The languages the apps speak: the setting's value, and its name in that language (a picker shows it so).
    public static readonly IReadOnlyList<(string Code, string Name)> Languages =
    [
        ("en", "English"),
        ("es-419", "Español (Latinoamérica)"),
    ];

    /// The Defaults key: "" or missing follows Windows, else one of `Languages`.
    public const string SettingKey = "language";

    static IReadOnlyDictionary<string, string> _table = new Dictionary<string, string>();

    /// The language in use ("en" when nothing is translated).
    public static string Language { get; private set; } = "en";

    /// How the holes' numbers are written: the language's, for showing only.
    public static CultureInfo Culture { get; private set; } = CultureInfo.GetCultureInfo("en-US");

    /// Picks the language once, at startup, before any view is built: the setting, else Windows's own (any Spanish
    /// gets the Latin American one: the only Spanish there is). A change takes effect at the next start.
    public static void Start(string? setting, CultureInfo? system = null) => Use(Resolve(setting, system ?? CultureInfo.CurrentUICulture));

    /// The language a setting and Windows's display language come to.
    public static string Resolve(string? setting, CultureInfo system)
    {
        if (Languages.Any(l => l.Code == setting)) return setting!;
        for (var c = system; !string.IsNullOrEmpty(c.Name); c = c.Parent)
            if (Languages.FirstOrDefault(l => l.Code.Equals(c.Name, StringComparison.OrdinalIgnoreCase)).Code is { } exact) return exact;
        return system.TwoLetterISOLanguageName == "es" ? "es-419" : "en";
    }

    /// Switches to `language` (tests, and Start).
    public static void Use(string language)
    {
        Language = language;
        _table = language == "en" ? new Dictionary<string, string>() : Table(language) ?? new Dictionary<string, string>();
        Culture = CultureInfo.GetCultureInfo(language == "en" ? "en-US" : language);
        CultureInfo.DefaultThreadCurrentUICulture = Culture;  // WinUI's own words (Cancel in a picker, …) where it has them
        CultureInfo.CurrentUICulture = Culture;
    }

    /// A language's table, from the embedded Strings/<language>.json: {"English": "translation", …}.
    public static IReadOnlyDictionary<string, string>? Table(string language)
    {
        using var stream = typeof(Strings).Assembly.GetManifestResourceStream($"AmadeusKit.Strings.{language}.json");
        if (stream is null) return null;
        using var memory = new MemoryStream();
        stream.CopyTo(memory);
        if (JSONValue.ParseObject(memory.ToArray()) is not { } values) return null;
        return values.Where(p => p.Value.String is { Length: > 0 } && !p.Key.StartsWith("//", StringComparison.Ordinal))
                     .ToDictionary(p => p.Key, p => p.Value.String!);
    }

    /// `english` in the language in use.
    public static string L(string english) => _table.TryGetValue(english, out var t) ? t : english;

    /// `format` (English, with {0}, {1:0.0}, …) in the language in use, its holes filled in that language's way.
    public static string L(string format, params object?[] values) => string.Format(Culture, L(format), values);

    /// A number for showing: `2.5` as "2.5" in English, as that language writes it otherwise.
    public static string Number(double value, string format = "0.##") => value.ToString(format, Culture);
}
