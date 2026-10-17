// The Show and Engine pages' logic (the app's Show/ShowLogic.cs): the night's clock and knobs, the messages to
// the engine, the timeline's maths, the words the cards use, the log's filter and follow.
using AmadeusDMX;

namespace AmadeusKit.Tests;

public class ShowLogicTests
{
    static ArcStatus Arc(string json) => ArcStatus.From(System.Text.Json.JsonDocument.Parse(json).RootElement);

    const string ArcJson = """
        {"on": true, "length": 18000, "elapsed": 3725, "stage": "peak",
         "stages": [["warmup", "Warm-up"], ["build", "Build"], ["peak", "Peak Time"]],
         "event": "club", "events": [["club", "Club Night"], ["wedding", "Wedding"]], "locked": false,
         "heat": 0.7, "trend": 0.05, "bpm": 127.6, "base_bpm": 118.4,
         "values": {"groups": 0.5, "specials": 0.2, "intensity": 0.875}, "manual": ["intensity"],
         "groups": 4, "playing": 2, "movement_level": 1, "hold": 4}
        """;

    [Fact]
    public void TheNightsClock()
    {
        Assert.Equal("1:30", Night.Hm(5400));
        Assert.Equal("0:00", Night.Hm(-20));
        Assert.Equal("1:02:05", Night.Hms(3725.9));
        var arc = Arc(ArcJson);
        Assert.Equal("1:02 of 5:00", Night.Clock(arc));
        Assert.Equal("3:57:55", Night.Countdown(arc));
        Assert.Equal("Peak Time", Night.Title(arc));
        Assert.False(Night.Over(arc));
        Assert.Equal("You hold 1 knob", Night.HeldHelp(arc));
        var before = arc with { Elapsed = null };
        Assert.Equal("starts with the music · 5:00", Night.Clock(before));
        Assert.Null(Night.Countdown(before));
        var over = arc with { Elapsed = 18300 };
        Assert.Equal("+0:05:00", Night.Countdown(over));
        Assert.True(Night.Over(over));
        Assert.Equal("Show Arc Off", Night.Title(arc with { On = false }));
        Assert.Equal(" (118 BPM). The stages are detected from it.", Night.HeatHelp(arc)[^44..]);
        Assert.Equal("arrow.up.right", Night.HeatSymbol(arc));
        Assert.Equal("arrow.right", Night.HeatSymbol(arc with { Trend = 0 }));
    }

    [Fact]
    public void ARealNightBeforeTheMusic()
    {
        // the arc of `amadeus live` before the first track (a lite frame's "arc", captured from the engine)
        var arc = Arc(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Samples", "arc-club.json")));
        Assert.Equal("Warm-Up", Night.Title(arc));
        Assert.Equal("starts with the music · 4:00", Night.Clock(arc));
        Assert.Null(Night.Countdown(arc));
        Knob K(string id) => Knob.All.Single(k => k.Id == id);
        Assert.Equal("calm", Night.KnobValue(K("movement"), arc, Night.KnobLevel(K("movement"), arc)));
        Assert.Equal("÷8", Night.KnobValue(K("changes"), arc, Night.KnobLevel(K("changes"), arc)));
        Assert.Equal("box", Night.KnobValue(K("specials"), arc, Night.KnobLevel(K("specials"), arc)));
        Assert.Equal("100", Night.KnobValue(K("intensity"), arc, Night.KnobLevel(K("intensity"), arc)));
        // every knob the card shows is one the engine reports
        Assert.All(Knob.All, k => Assert.True(arc.Values.ContainsKey(k.Id), k.Id));
        Assert.Equal(4, arc.Events.Count);
    }

    [Fact]
    public void KnobsSayWhatTheirLevelMeans()
    {
        var arc = Arc(ArcJson);
        Knob K(string id) => Knob.All.Single(k => k.Id == id);
        Assert.Equal(11, Knob.All.Count());
        Assert.Equal(["In Play", "Character", "Reaction", "Level"], Knob.Sections.Select(s => s.Title));
        Assert.Equal("mid", Night.KnobValue(K("movement"), arc, 0.3));
        Assert.Equal("full", Night.KnobValue(K("movement"), arc with { MovementLevel = null }, 0.3));
        Assert.Equal("÷4", Night.KnobValue(K("changes"), arc, 0.3));
        Assert.Equal("all", Night.KnobValue(K("changes"), arc with { Hold = 1 }, 0.3));
        Assert.Equal("", Night.KnobValue(K("changes"), arc with { Hold = null }, 0.3));
        Assert.Equal("box", Night.KnobValue(K("specials"), arc, 0.2));
        Assert.Equal("drops", Night.KnobValue(K("specials"), arc, 0.5));
        Assert.Equal("free", Night.KnobValue(K("specials"), arc, 0.75));
        Assert.Equal("88", Night.KnobValue(K("intensity"), arc, 0.875));
        Assert.Equal(0.875, Night.KnobLevel(K("intensity"), arc));
        Assert.Equal(1, Night.KnobLevel(K("smoke"), arc));  // not reported: full
        Assert.EndsWith("(2 of 4 playing)", Night.KnobHelp(K("groups"), arc));
        Assert.True(Night.CanShorten(arc) && Night.CanLengthen(arc));
        Assert.False(Night.CanShorten(arc with { Length = 1800 }));
        Assert.False(Night.CanLengthen(arc with { Length = 12 * 3600 }));
    }

    [Fact]
    public void ADraggedKnobShowsWhereItIsHeld()
    {
        var d = new KnobDraft();
        Assert.Equal(0.4, d.Shown(0.4));
        d.Move(0.9);
        Assert.Equal(0.9, d.Shown(0.4));
        d.End();
        Assert.Equal(0.4, d.Shown(0.4));
    }

    [Fact]
    public void ArcMessagesAsTheEngineReadsThem()
    {
        Assert.Equal("""{"type":"arc","knob":{"intensity":0.7}}""", ArcMessage.Json(ArcMessage.Knob("intensity", 0.7)));
        Assert.Equal("""{"type":"arc","auto":"all"}""", ArcMessage.Json(ArcMessage.Auto("all")));
        Assert.Equal("""{"type":"arc","stage":"peak"}""", ArcMessage.Json(ArcMessage.Stage("peak")));
        Assert.Equal("""{"type":"arc","lock":true}""", ArcMessage.Json(ArcMessage.Lock(true)));
        Assert.Equal("""{"type":"arc","length_s":17100}""", ArcMessage.Json(ArcMessage.Length(18000 - Night.Step)));
        Assert.Equal("""{"type":"arc","event":"wedding"}""", ArcMessage.Json(ArcMessage.Event("wedding")));
        Assert.Equal("""{"type":"arc","enabled":false}""", ArcMessage.Json(ArcMessage.Enabled(false)));
        Assert.Equal("""{"type":"arc","reset":true}""", ArcMessage.Json(ArcMessage.Reset()));
    }

    static Hello Track() => Hello.From(System.Text.Json.JsonDocument.Parse("""
        {"track": "Deck 1: track.mp3", "duration": 100, "bpm": 128, "energy": [0, 0.5, 1],
         "plan": [{"phrase": 0, "start": 0, "end": 40, "section": "intro", "par_base": "glow", "par_accent": "hit",
                   "movement": "slow_sweep", "aim": "crowd", "palette": "cool"},
                  {"phrase": 1, "start": 40, "end": 100, "section": "drop", "drop_score": 0.9, "palette": "fire",
                   "probabilities": {"movement": {"a": 0.1, "b": 0.6, "c": 0.3}}, "confidence": {"section": 0.5}}]}
        """).RootElement);

    [Fact]
    public void TheTimelinesMaths()
    {
        var h = Track();
        Assert.Equal(50, Timeline.X(25, 100, 200));
        Assert.Equal(25, Timeline.Time(50, 200, 100));
        Assert.Equal(0, Timeline.Time(50, 0, 100));
        Assert.Equal(99, Timeline.PlayheadX(50, 100, 200));
        Assert.Equal(199, Timeline.PlayheadX(500, 100, 200));  // kept in the timeline
        Assert.Equal(-1, Timeline.PlayheadX(-5, 100, 200));
        Assert.Equal((80, 119), Timeline.Bar(h.Plan[1], h, 200));
        var e = Timeline.Energy(h.Energy, 200, 54);
        Assert.Equal([(0, 39), (0, 39), (100, 39 - 0.5 * 36), (200, 3), (200, 39)], e);
        Assert.Empty(Timeline.Energy([0.4], 200, 54));
        Assert.Equal([1], Timeline.Drops(h).Select(d => d.Phrase));
        Assert.Equal("0:00 · intro · pars glow + hit · heads slow_sweep / crowd · cool", Timeline.Describe(h.Plan[0]));
        Assert.Equal("0:40 · drop ⚡ · pars – + – · heads – / – · fire", Timeline.Describe(h.Plan[1]));
        Assert.Equal(1, h.PhraseIndex(Timeline.Time(150, 200, h.Duration)));
    }

    [Fact]
    public void NowPlayingWords()
    {
        var h = Track();
        Assert.Null(NowPlaying.At(h, 2));
        Assert.Null(NowPlaying.At(h, -1));
        var next = NowPlaying.At(h, 1)!;
        Assert.Equal("⚡ 12s", NowPlaying.NextValue(next, 27.5));
        Assert.Equal("⚡ drop in 0 s", NowPlaying.NextLine(next, 45));
        Assert.Equal("intro in 0 s", NowPlaying.NextLine(h.Plan[0], 3));
        Assert.True(NowPlaying.GuardIsSevere("blanked: in zone"));
        Assert.False(NowPlaying.GuardIsSevere("raised 0.4 m"));
        Assert.Equal(["a", "b"], NowPlaying.Guard(new Dictionary<string, string> { ["b"] = "x", ["a"] = "y" }).Select(g => g.Id));
    }

    [Fact]
    public void TheDecksPreparation()
    {
        var s = new TrackStatus { Analysis = "done", Stems = "running", Elapsed = 75, Ai = "running", AiDone = 3, Stream = "spotify", Copy = "waiting", Lights = "rules" };
        var steps = Decks.Steps(s);
        Assert.Equal(["Spotify copy", "Analysis", "Instruments 1:15", "AI 3/…"], steps.Select(x => x.Text));
        Assert.Equal(["running", "done", "running", "running"], steps.Select(x => x.State));
        Assert.Equal(Tone.Green, steps[1].Tone);
        Assert.Equal("checkmark", steps[1].Symbol);
        Assert.Equal("circle.dotted", new Decks.Step("AI", null).Symbol);
        Assert.Equal(Tone.Secondary, new Decks.Step("AI", "n/a").Tone);
        Assert.Equal("quick plan", Decks.Lights("rules"));
        Assert.Equal("±4 ms · 2 lost", Decks.LinkLine(new LinkStatus { Name = "DJ", Up = true, JitterMs = 3.6, Lost = 2 }));
        Assert.Equal("link down", Decks.LinkLine(new LinkStatus { Name = "DJ" }));
        // the volume moves without changing the card's shape
        DeckInfo D(double vol) => new() { Deck = 1, Track = "a", Vol = vol, Play = true, Status = s };
        Assert.Equal(Decks.Shape([D(0.2)], null), Decks.Shape([D(0.9)], null));
        Assert.NotEqual(Decks.Shape([D(0.2)], null), Decks.Shape([D(0.2) with { Play = false }], null));
    }

    [Fact]
    public void TheDirectorsWords()
    {
        var h = Track();
        Assert.Equal("AI (Decisions API)", Director.Source("openai"));
        Assert.Equal("Local AI", Director.Source("ollama:llama3"));
        Assert.Equal("Rules", Director.Source("rules"));
        Assert.Null(Director.BestProbabilities(h.Plan[0]));
        var p = Director.BestProbabilities(h.Plan[1])!.Value;
        Assert.Equal("movement", p.Title);
        Assert.Equal(["b", "c", "a"], p.Values.Select(v => v.Key));
        Assert.Equal("slow sweep", Director.Value(h.Plan[0], "movement"));
        Assert.Equal(Tone.Orange, Director.Confidence(0.5));
        Assert.Equal(Tone.Green, Director.Confidence(0.6));
        Assert.Equal(Tone.Red, Director.Confidence(0.39));
        Assert.False(Director.ShowsFeatured(h.Plan[0]));
        Assert.Equal(1, Director.Shown(null, 5, 2));
        Assert.Equal(0, Director.Shown(0, 1, 2));
        var deck = new DeckInfo { Deck = 1, Status = new TrackStatus { Lights = "rules", Ai = "running", AiDone = 2, AiTotal = 9 } };
        Assert.Contains("(2/9 phrases)", Director.RulesNote([deck]));
        Assert.StartsWith("The rule-based director", Director.RulesNote([]));
    }

    [Fact]
    public void GenreChips()
    {
        Assert.Equal("TECHNO", Genre.Chip("techno", ""));
        Assert.Equal("POP → HOUSE", Genre.Chip("pop", "house"));
        Assert.Equal("POP", Genre.Chip("pop", "pop"));
        Assert.Equal("Genre: pop. From the file's genre tag. Lit in the set's house style, so the set looks like one show.", Genre.ChipHelp("pop", "tag", "house"));
        Assert.Equal("guitars", Genre.Symbol("metal"));
        Assert.Equal("waveform", Genre.Symbol("techno"));
    }

    static EngineProcess.LogLine L(int id, string text, bool error = false) => new(id, DateTime.Now, text, error);

    [Fact]
    public void TheLogFiltersAndFollows()
    {
        Assert.Equal(Tone.Red, EngineLog.Tone(L(0, "✓ fine", error: true)));
        Assert.Equal(Tone.Green, EngineLog.Tone(L(0, "✓ fine")));
        Assert.Equal(Tone.Orange, EngineLog.Tone(L(0, "⚠ hmm")));
        Assert.Equal(Tone.Primary, EngineLog.Tone(L(0, "hello")));
        List<EngineProcess.LogLine> log = [L(1, "Analysis"), L(2, "deck A"), L(3, "analysis done")];
        Assert.Equal([1, 3], EngineLog.Filter(log, "ANALYSIS").Select(l => l.Id));
        // first time: everything
        var c = EngineLog.Sync([], log, "");
        Assert.True(c.Reset);
        Assert.Equal(3, c.Append.Count);
        // grew: the new lines only
        log.Add(L(4, "more"));
        c = EngineLog.Sync([1, 2, 3], log, "");
        Assert.False(c.Reset);
        Assert.Equal(0, c.DropFront);
        Assert.Equal([4], c.Append.Select(l => l.Id));
        // the oldest went (the log keeps its last lines)
        log.RemoveAt(0);
        c = EngineLog.Sync([1, 2, 3, 4], log, "");
        Assert.Equal((false, 1, 0), (c.Reset, c.DropFront, c.Append.Count));
        // cleared, or filtered differently: start again
        Assert.True(EngineLog.Sync([2, 3, 4], [], "").Reset);
        Assert.True(EngineLog.Sync([2, 3, 4], log, "analysis").Reset);
        Assert.Equal(["The Show Engine Hasn’t Run Yet", "Setup Service Not Started"], new[] { EngineLog.Empty(true), EngineLog.Empty(false) });
    }

    [Fact]
    public void ThePairingCode()
    {
        Assert.Equal("1234", PairingCode.Clean("12a34 5"));
        Assert.Equal("", PairingCode.Clean("abc"));
        Assert.False(PairingCode.CanConnect(null, "1234"));
        Assert.False(PairingCode.CanConnect("DJ", "123"));
        Assert.True(PairingCode.CanConnect("DJ", "1234"));
        Assert.Equal("DJ", PairingCode.AutoChoose(null, [new LinkBrowser.DJ("DJ")]));
        Assert.Null(PairingCode.AutoChoose(null, [new LinkBrowser.DJ("A"), new LinkBrowser.DJ("B")]));
        Assert.Equal("A", PairingCode.AutoChoose("A", [new LinkBrowser.DJ("B")]));
    }
}
