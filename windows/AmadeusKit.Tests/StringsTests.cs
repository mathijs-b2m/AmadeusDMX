// The words in other languages (AmadeusKit/Strings.cs): every L("…") in the apps has a translation in each table,
// with the same {0} holes, and no table keeps words the apps no longer say. A failure lists what to translate.
using System.Globalization;
using System.Text.RegularExpressions;

public sealed class StringsTests
{
    static readonly string Windows = Path.Combine(AmadeusKit.Tests.EditorWorkspace.RepoRoot, "windows");

    /// Every L("…") key in the apps' code (comments left out), as the running app sees it.
    static HashSet<string> Keys()
    {
        var keys = new HashSet<string>();
        var call = new Regex(@"\bL\(""((?:[^""\\\n]|\\.)*)""");
        foreach (var project in new[] { "AmadeusDMX", "AmadeusKit", "AmadeusLink" })
            foreach (var file in Directory.EnumerateFiles(Path.Combine(Windows, project), "*.cs", SearchOption.AllDirectories))
            {
                if (file.Contains($"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}")
                    || file.Contains($"{Path.DirectorySeparatorChar}bin{Path.DirectorySeparatorChar}")) continue;
                foreach (var line in File.ReadLines(file))
                {
                    var code = line.Trim().StartsWith("//", StringComparison.Ordinal) ? "" : line.Split(" // ")[0];
                    foreach (Match m in call.Matches(code)) keys.Add(Regex.Unescape(m.Groups[1].Value));
                }
            }
        return keys;
    }

    static IEnumerable<string> Holes(string s) => Regex.Matches(s, @"\{(\d+)[^}]*\}").Select(m => m.Groups[1].Value).Distinct().Order();

    public static IEnumerable<object[]> Translated() => Strings.Languages.Where(l => l.Code != "en").Select(l => new object[] { l.Code });

    [Theory, MemberData(nameof(Translated))]
    public void EveryShownWordIsTranslated(string language)
    {
        var table = Strings.Table(language);
        Assert.NotNull(table);
        var missing = Keys().Where(k => !table.ContainsKey(k)).Order().ToList();
        Assert.True(missing.Count == 0, $"Not in Strings/{language}.json yet:\n" + string.Join("\n", missing));
    }

    [Theory, MemberData(nameof(Translated))]
    public void TranslationsKeepTheirValues(string language)
    {
        var wrong = Strings.Table(language)!.Where(p => !Holes(p.Key).SequenceEqual(Holes(p.Value))).Select(p => p.Key).ToList();
        Assert.True(wrong.Count == 0, "Holes differ from the English:\n" + string.Join("\n", wrong));
    }

    [Theory, MemberData(nameof(Translated))]
    public void NoWordsTheAppsNoLongerSay(string language)
    {
        var keys = Keys();
        var stale = Strings.Table(language)!.Keys.Where(k => !keys.Contains(k)).Order().ToList();
        Assert.True(stale.Count == 0, $"In Strings/{language}.json but no longer in the code (reworded?):\n" + string.Join("\n", stale));
    }

    [Fact]
    public void LanguageFollowsTheSettingThenWindows()
    {
        Assert.Equal("es-419", Strings.Resolve("es-419", CultureInfo.GetCultureInfo("nl-NL")));
        Assert.Equal("en", Strings.Resolve("en", CultureInfo.GetCultureInfo("es-MX")));
        Assert.Equal("es-419", Strings.Resolve(null, CultureInfo.GetCultureInfo("es-MX")));
        Assert.Equal("es-419", Strings.Resolve("", CultureInfo.GetCultureInfo("es-ES")));  // the only Spanish there is
        Assert.Equal("en", Strings.Resolve(null, CultureInfo.GetCultureInfo("nl-NL")));
        Assert.Equal("en", Strings.Resolve("klingon", CultureInfo.GetCultureInfo("en-GB")));
    }

    [Fact]
    public void SpanishFillsItsHolesItsOwnWay()
    {
        try
        {
            Strings.Use("es-419");
            Assert.Equal("Configuración", L("Settings"));
            Assert.Equal("¿Instalar Show packs?", L("Install {0}?", "Show packs"));
            Assert.Equal("Not in any table", L("Not in any table"));  // untranslated: the English
        }
        finally { Strings.Use("en"); }
        Assert.Equal("Settings", L("Settings"));
        Assert.Equal("Install X?", L("Install {0}?", "X"));
    }
}
