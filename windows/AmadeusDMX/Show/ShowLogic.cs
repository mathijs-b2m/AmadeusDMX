// What the Show and Engine pages work out, apart from drawing it: the words, the numbers, the timeline's maths,
// the show arc's knobs and the messages they send. Plain C# (no WinUI): the kit's tests compile this file too.
using System.Globalization;
using System.Text.Json;
using AmadeusKit;

namespace AmadeusDMX;

/// A colour a view gives a value, by meaning (the view maps it to the theme: Tint.Green, the secondary text, …).
public enum Tone { Primary, Secondary, Green, Orange, Red, Yellow }

static class Num
{
    /// Swift's `Int(x.rounded())`: half away from zero.
    public static int Round(double x) => (int)Math.Round(x, MidpointRounding.AwayFromZero);

    /// Swift's `Int(x)`: towards zero.
    public static int Trunc(double x) => (int)Math.Truncate(x);

    public static string Pct(double v) => $"{Round(v * 100)}%";
}

// MARK: the night (NightCard)

/// One of the show arc's knobs, as the engine names it.
public sealed record Knob(string Id, string Title, string Symbol, string Help, bool Toggle = false)
{
    /// The knobs as a lighting director thinks of them: what is in play tonight, the character of each track,
    /// how hard the lights react, and the master level.
    public static readonly IReadOnlyList<(string Title, IReadOnlyList<Knob> Knobs)> Sections =
    [
        ("In Play", [
            new("groups", "Light Groups", "square.grid.2x2",
                "How many groups of lights play: washes first, then the heads, the biggest group last. A group that hasn't played yet tonight is a surprise: it comes out on a drop. All the way down: none"),
            new("specials", "Special Effects", "sparkles",
                "Lasers, strobes and blinders: in the box (off), out for the big moments only (the drops), or free (as the director plans them)"),
            new("screen", "LED Wall", "tv",
                "The LED wall: below half only calm colour (no characters, words or psychedelics), at zero off"),
            new("smoke", "Smoke", "cloud.fog", "How much of the planned smoke goes out"),
        ]),
        ("Character", [
            new("movement", "Movement", "arrow.up.and.down.and.arrow.left.and.right",
                "How busy the heads are: calm (slow sweeps and circles, beams stay on), mid (no wild paths), full (the director's beat-locked jumps). Each change re-plans the tracks in a few seconds"),
            new("changes", "Look Changes", "rectangle.stack",
                "How often the look changes within a song: low holds one look for up to eight phrases, high changes with every part the analysis finds. Re-plans the tracks in a few seconds"),
            new("colour", "Colour Variety", "paintpalette",
                "How much colour moves: low keeps a palette for several phrases, high swaps every eight bars"),
        ]),
        ("Reaction", [
            new("response", "Beat Response", "waveform.path",
                "How hard the lights hit with the beat: low glows and breathes, high punches every kick"),
            new("drops", "Drops", "arrow.down.to.line",
                "How big a drop lands: low a lift and (above a quarter) its own look; from a third a breath of darkness; full: blackout, bang, flash (as the director plans it)"),
            new("flashes", "Flashes", "bolt", "White flash accents and strobes"),
        ]),
        ("Level", [
            new("intensity", "Intensity", "sun.max", "The master: how bright the whole rig plays. All the way down: dark"),
        ]),
    ];

    public static IEnumerable<Knob> All => Sections.SelectMany(s => s.Knobs);
}

public static class Night
{
    /// 5400 s → "1:30" (hours and minutes).
    public static string Hm(double s)
    {
        var m = Math.Max(0, Num.Trunc(s / 60));
        return $"{m / 60}:{m % 60:00}";
    }

    /// 5400 s → "1:30:00".
    public static string Hms(double s)
    {
        var t = Math.Max(0, Num.Trunc(s));
        return $"{t / 3600}:{t % 3600 / 60:00}:{t % 60:00}";
    }

    /// Under the stage's name: how far the night is.
    public static string Clock(ArcStatus arc) =>
        arc.Elapsed is { } e ? $"{Hm(e)} of {Hm(arc.Length)}" : $"starts with the music · {Hm(arc.Length)}";

    /// The countdown (nil before the night started); over the length: "+0:05:00".
    public static string? Countdown(ArcStatus arc) => arc.Remaining is { } left ? (left >= 0 ? Hms(left) : "+" + Hms(-left)) : null;

    public static bool Over(ArcStatus arc) => arc.Remaining is < 0;

    public static string Title(ArcStatus arc) => arc.On ? arc.StageName : "Show Arc Off";

    public static string HeldHelp(ArcStatus arc) => $"You hold {arc.Manual.Count} knob{(arc.Manual.Count == 1 ? "" : "s")}";

    /// What a knob's row says at its right: its level, or what the level means for that knob.
    public static string KnobValue(Knob knob, ArcStatus arc, double value) => knob.Id switch
    {
        "movement" => new[] { "calm", "mid", "full" }[Math.Min(2, Math.Max(0, arc.MovementLevel ?? 2))],
        "changes" => arc.Hold is { } h ? (h <= 1 ? "all" : $"÷{h}") : "",
        "specials" => value < 0.25 ? "box" : value < 0.75 ? "drops" : "free",
        _ => $"{Num.Round(value * 100)}",
    };

    /// The knob's value as the arc has it (a knob the engine doesn't report: full).
    public static double KnobLevel(Knob knob, ArcStatus arc) => arc.Values.TryGetValue(knob.Id, out var v) ? v : 1;

    public static string KnobHelp(Knob knob, ArcStatus arc) =>
        knob.Id == "groups" ? $"{knob.Help} ({arc.Playing} of {arc.Groups} playing)" : knob.Help;

    public static string HeatSymbol(ArcStatus arc) => arc.Trend > 0.02 ? "arrow.up.right" : arc.Trend < -0.02 ? "arrow.down.right" : "arrow.right";

    public static string HeatHelp(ArcStatus arc) =>
        "How hot the mix runs: the tracks' energy and the tempo against tonight's warm-up tempo"
        + (arc.BaseBpm is { } b ? $" ({Num.Round(b)} BPM)" : "") + ". The stages are detected from it.";

    /// A night is between half an hour and twelve hours, a quarter of an hour per click.
    public const double Step = 900, MinLength = 1800, MaxLength = 12 * 3600;
    public static bool CanShorten(ArcStatus arc) => arc.Length > MinLength;
    public static bool CanLengthen(ArcStatus arc) => arc.Length < MaxLength;
}

/// The messages the Night card sends the engine over the feed: `{"type": "arc", …}` (docs/protocols.md).
public static class ArcMessage
{
    public static Dictionary<string, object> Make(string key, object value) => new() { ["type"] = "arc", [key] = value };

    public static Dictionary<string, object> Knob(string id, double value) => Make("knob", new Dictionary<string, double> { [id] = value });
    public static Dictionary<string, object> Auto(string id) => Make("auto", id);          // a knob, or "all"
    public static Dictionary<string, object> Stage(string key) => Make("stage", key);
    public static Dictionary<string, object> Lock(bool on) => Make("lock", on);
    public static Dictionary<string, object> Length(double seconds) => Make("length_s", seconds);
    public static Dictionary<string, object> Event(string key) => Make("event", key);
    public static Dictionary<string, object> Enabled(bool on) => Make("enabled", on);
    public static Dictionary<string, object> Reset() => Make("reset", true);

    /// As it goes on the wire.
    public static string Json(Dictionary<string, object> m) => JsonSerializer.Serialize(m, SetupAPI.JsonOptions);
}

/// A knob's slider while it is dragged: it shows where you hold it, not the arc's (older) echo of it.
public sealed class KnobDraft
{
    public double? Draft { get; private set; }

    /// The value to show: the draft while there is one, else the arc's.
    public double Shown(double arcValue) => Draft ?? arcValue;

    public void Move(double v) => Draft = v;

    /// The drag ended (Swift's `onEditingChanged(false)`): the arc's value counts again.
    public void End() => Draft = null;
}

// MARK: the timeline (TimelineCard)

public static class Timeline
{
    public const double BarHeight = 12;
    public const double DropScore = 0.6;

    static double Dur(Hello h) => Math.Max(h.Duration, 1);

    /// Where a time is across the width.
    public static double X(double t, double duration, double width) => t / Math.Max(duration, 1) * width;

    /// The time at a point across the width (a click, the pointer).
    public static double Time(double x, double width, double duration) => width <= 0 ? 0 : x / width * duration;

    /// The playhead's left edge: the time's x, kept in the timeline, minus half its 2 px.
    public static double PlayheadX(double t, double duration, double width) =>
        width * Math.Min(1, Math.Max(0, t / Math.Max(duration, 1))) - 1;

    /// A phrase's bar: x, width (1 px gap; at least 1 px).
    public static (double X, double Width) Bar(Decision d, Hello h, double width)
    {
        var x0 = d.Start / Dur(h) * width;
        var x1 = d.End / Dur(h) * width;
        return (x0, Math.Max(1, x1 - x0 - 1));
    }

    /// The loudness curve above the bars: the points of its outline, from the baseline at the left to the
    /// baseline at the right (filled and stroked).
    public static IReadOnlyList<(double X, double Y)> Energy(IReadOnlyList<double> e, double width, double height)
    {
        if (e.Count <= 1) return [];
        var baseY = height - BarHeight - 3;
        var span = height - BarHeight - 6;
        var pts = new List<(double, double)>(e.Count + 2) { (0, baseY) };
        for (var i = 0; i < e.Count; i++) pts.Add((i / (double)(e.Count - 1) * width, baseY - e[i] * span));
        pts.Add((width, baseY));
        return pts;
    }

    public static IEnumerable<Decision> Drops(Hello h) => h.Plan.Where(d => d.DropScore >= DropScore);

    /// What the header says for the phrase under the pointer.
    public static string Describe(Decision d) =>
        $"{Formatting.TimeString(d.Start)} · {d.Section}{(d.DropScore >= DropScore ? " ⚡" : "")} · pars {d["par_base"]} + {d["par_accent"]}"
        + $" · heads {d["movement"]} / {d["aim"]} · {d.Palette}";
}

// MARK: now playing (NowPlayingCard, PerformBoard)

public static class NowPlaying
{
    public static Decision? At(Hello h, int i) => i >= 0 && i < h.Plan.Count ? h.Plan[i] : null;

    public static bool IsDrop(Decision next) => next.DropScore >= Timeline.DropScore || next.Section == "drop";

    /// Seconds to the next phrase (never negative).
    public static double Left(Decision next, double time) => Math.Max(0, next.Start - time);

    /// The "next" metric: "⚡ 12s" before a drop, else "12s".
    public static string NextValue(Decision next, double time) =>
        (IsDrop(next) ? "⚡ " : "") + $"{Num.Trunc(Left(next, time))}s";

    /// The Perform board's line: "⚡ drop in 12 s".
    public static string NextLine(Decision next, double time) =>
        (IsDrop(next) ? "⚡ " : "") + $"{next.Section} in {Num.Trunc(Left(next, time))} s";

    public static bool GuardIsSevere(string note) => note.StartsWith("blanked", StringComparison.Ordinal) || note.StartsWith("dark", StringComparison.Ordinal);

    /// The laser guard's notes, by laser.
    public static IEnumerable<(string Id, string Note)> Guard(IReadOnlyDictionary<string, string> g) =>
        g.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => (p.Key, p.Value));

    /// The Perform board's output line.
    public static string Output(SetSummary? set) =>
        set is null ? "No set" : set.IsVirtual ? "No lights in this set (visualiser only)" : set.OutputText;
}

// MARK: the decks (DecksCard)

public static class Decks
{
    public static string LinkLine(LinkStatus link) =>
        link.Up ? $"±{link.JitterMs.ToString("F0", CultureInfo.InvariantCulture)} ms · {link.Lost} lost" : "link down";

    public static string Lights(string l) => l switch { "openai" => "AI plan", "rules" => "quick plan", "tempo" => "tempo groove", _ => l };

    /// A preparation step: its title with progress, and its state's symbol and colour.
    public sealed record Step(string Title, string? State, string? Extra = null)
    {
        public string Text => Extra is null ? Title : $"{Title} {Extra}";

        public string Symbol => State switch
        {
            "done" => "checkmark",
            "running" => "arrow.triangle.2.circlepath",
            "failed" => "exclamationmark.triangle",
            "n/a" => "minus",
            _ => "circle.dotted",
        };

        public Tone Tone => State switch { "done" => Tone.Green, "running" => Tone.Orange, "failed" => Tone.Red, _ => Tone.Secondary };
    }

    /// The chips for a deck's track: the streamed copy (if any), analysis, instruments, AI.
    public static IReadOnlyList<Step> Steps(TrackStatus s)
    {
        var steps = new List<Step>();
        if (s.Stream is { } stream) steps.Add(new($"{Formatting.Capitalized(stream)} copy", s.Copy == "waiting" ? "running" : s.Copy));
        steps.Add(new("Analysis", s.Analysis));
        steps.Add(new("Instruments", s.Stems, s.Stems == "running" && s.Elapsed is { } e ? Formatting.TimeString(e) : null));
        steps.Add(new("AI", s.Ai, s.Ai == "running" ? $"{s.AiDone ?? 0}/{s.AiTotal?.ToString(CultureInfo.InvariantCulture) ?? "…"}" : null));
        return steps;
    }

    /// What the card shows, without the volumes and the link's numbers (which move all the time): the card is rebuilt only when this changes.
    public static string Shape(IReadOnlyList<DeckInfo> decks, LinkStatus? link) =>
        string.Join("|", decks.Select(d => $"{d.Deck}:{d.Track}:{d.Play}:{d.Genre}:{d.Style}:{d.Status}"))
        + (link is null ? "" : $"#{link.Name}:{link.Up}:{string.Join(",", link.Fetching)}");
}

// MARK: the director (DirectorInspector)

public static class Director
{
    public static string Source(string s) => s switch
    {
        "openai" => "AI (Decisions API)",
        "openai+hold" => "AI, unsure: held the look",
        "rules" => "Rules",
        _ => s.StartsWith("ollama", StringComparison.Ordinal) ? "Local AI" : s,
    };

    /// Under a rules plan: why there are no probabilities (yet).
    public static string RulesNote(IReadOnlyList<DeckInfo> decks)
    {
        var st = decks.Select(d => d.Status).FirstOrDefault(s => s?.Lights == "rules");
        if (st?.Ai == "running")
            return $"Quick plan for now: the AI is still deciding this track ({st.AiDone ?? 0}/{st.AiTotal?.ToString(CultureInfo.InvariantCulture) ?? "…"} phrases). It takes over when it is done.";
        if (st?.Stems == "running") return "Quick plan for now: the instruments are separated first, then the AI decides.";
        return "The rule-based director has no probabilities. Choose an AI director in the set's settings to see how sure it is.";
    }

    /// The first decision with probabilities, its five likeliest choices.
    public static (string Title, IReadOnlyList<(string Key, double P)> Values)? BestProbabilities(Decision d)
    {
        foreach (var key in new[] { "par_accent", "movement", "section", "screen" })
            if (d.Probabilities.TryGetValue(key, out var p) && p.Count > 0)
                return (key.Replace('_', ' '), p.OrderByDescending(x => x.Value).Take(5).Select(x => (x.Key, x.Value)).ToList());
        return null;
    }

    /// A decision's value for people: "slow_sweep" → "slow sweep".
    public static string Value(Decision d, string key) => d[key].Replace('_', ' ');

    public static Tone Confidence(double v) => v >= 0.6 ? Tone.Green : v >= 0.4 ? Tone.Orange : Tone.Red;

    public static bool ShowsFeatured(Decision d) => d["featured"] != "–" && d["featured"].Length > 0;

    /// The phrase shown: the pinned one, else the one playing (always one of the plan's).
    public static int Shown(int? pinned, int playing, int count) => Math.Max(0, Math.Min(count - 1, pinned ?? playing));
}

// MARK: the genre (Genre.swift)

public static class Genre
{
    public static string Symbol(string genre) => genre switch
    {
        "cinematic" => "film.stack",
        "classical" => "music.quarternote.3",
        "ambient" => "cloud",
        "rock" or "metal" => "guitars",
        "hiphop" or "rnb" => "music.mic",
        "jazz" or "funk" => "music.note.list",
        "disco" => "sparkles",
        "pop" or "latin" or "reggaeton" => "music.note",
        _ => "waveform",
    };

    public static string Source(string s) => s switch
    {
        "you" => "Your choice",
        "ai" => "From the artist and title (Decisions API)",
        "tag" => "From the file's genre tag",
        _ => "From the audio: groove, bass and tempo",
    };

    static bool Restyled(string genre, string style) => style.Length > 0 && style != genre;

    /// "TECHNO"; "POP → HOUSE" when the set plays it in another genre's style.
    public static string Chip(string genre, string style) =>
        Restyled(genre, style) ? $"{genre.ToUpperInvariant()} → {style.ToUpperInvariant()}" : genre.ToUpperInvariant();

    public static string ChipHelp(string genre, string source, string style) =>
        $"Genre: {genre}. {Source(source)}."
        + (Restyled(genre, style) ? $" Lit in the set's {style} style, so the set looks like one show." : "");
}

// MARK: the engine's log (EngineView)

public static class EngineLog
{
    /// The lines with the filter in them (any case), or all.
    public static IReadOnlyList<EngineProcess.LogLine> Filter(IReadOnlyList<EngineProcess.LogLine> log, string filter) =>
        filter.Length == 0 ? log : log.Where(l => l.Text.Contains(filter, StringComparison.CurrentCultureIgnoreCase)).ToList();

    public static Tone Tone(EngineProcess.LogLine l) =>
        l.IsError ? AmadeusDMX.Tone.Red : l.Text.Contains('✓') ? AmadeusDMX.Tone.Green : l.Text.Contains('⚠') ? AmadeusDMX.Tone.Orange : AmadeusDMX.Tone.Primary;

    public static string Empty(bool show) => show ? "The Show Engine Hasn’t Run Yet" : "Setup Service Not Started";

    public static string EmptyDetail(bool show) =>
        show ? "Start a show (Ctrl+R) and its output appears here." : "It starts when the wizard or the rig tools need it.";

    /// How the list on screen follows the log: drop lines from its front (the log keeps its last 4000), add the
    /// new ones at its end; or, when the two no longer line up (cleared, a new filter), start again.
    public readonly record struct Change(bool Reset, int DropFront, IReadOnlyList<EngineProcess.LogLine> Append);

    public static Change Sync(IReadOnlyList<int> shown, IReadOnlyList<EngineProcess.LogLine> log, string filter)
    {
        var lines = Filter(log, filter);
        if (shown.Count == 0) return new(lines.Count > 0, 0, lines);
        if (lines.Count == 0) return new(true, 0, []);
        var first = lines[0].Id;
        var drop = 0;
        while (drop < shown.Count && shown[drop] < first) drop++;
        // what stays must be the start of the lines as they are now
        var kept = shown.Count - drop;
        if (kept > lines.Count) return new(true, 0, lines);
        for (var i = 0; i < kept; i++)
            if (lines[i].Id != shown[drop + i]) return new(true, 0, lines);
        return new(false, drop, lines.Skip(kept).ToList());
    }
}

// MARK: the DJ laptop (DJLinkSheet)

public static class PairingCode
{
    /// What the code field keeps of what is typed: digits, at most four.
    public static string Clean(string typed) => new([.. typed.Where(char.IsAsciiDigit).Take(4)]);

    public static bool CanConnect(string? chosen, string code) => chosen is not null && code.Length == 4;

    /// The one DJ nearby is chosen for you (unless you chose already).
    public static string? AutoChoose(string? chosen, IReadOnlyList<LinkBrowser.DJ> found) =>
        chosen ?? (found.Count == 1 ? found[0].Name : null);
}
