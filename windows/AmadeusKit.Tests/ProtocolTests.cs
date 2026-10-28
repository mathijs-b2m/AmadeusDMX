// The feed as the engine sends it: real hello and frame messages (Samples/, made by the engine for the test sets
// with the synthetic track) decode in full, and the decoders forgive exactly what the Swift ones forgive.
using System.Text;
using AmadeusKit;

namespace AmadeusKit.Tests;

public class ProtocolTests
{
    static string Sample(string name) => File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Samples", name));

    static Hello DecodeHello(string json) =>
        Assert.IsType<HelloMessage>(FeedMessage.Decode(json)).Hello;

    static Frame DecodeFrame(string json) =>
        Assert.IsType<FrameMessage>(FeedMessage.Decode(json)).Frame;

    // ported from mac/Tests/AmadeusKitTests/ArcStatusTests.swift
    [Fact]
    public void ArcStatusDecodesFromAnEngineFrame()
    {
        var json = """
            {"type": "frame", "lite": true, "t": 0, "phrase": 0, "arc": {"on": true, "length": 14400, "elapsed": 10.0,
             "stage": "warmup", "stages": [["warmup", "Dinner & Drinks"], ["build", "Opening the Floor"], ["peak", "Party"],
             ["deep", "Slow Dances"], ["finale", "Last Dances"], ["outro", "Goodnight"]], "event": "wedding",
             "events": [["club", "DJ Set / Club Night"], ["wedding", "Wedding"]], "locked": false, "heat": 0.628,
             "trend": 0.0, "bpm": 124.0, "base_bpm": 124.0, "values": {"groups": 0.4, "specials": 0.0, "response": 0.315,
             "smoke": 0.2, "colour": 0.2, "intensity": 0.565, "flashes": 0.0}, "manual": ["smoke"], "groups": 8, "playing": 8}}
            """;
        var f = DecodeFrame(json);
        var arc = Assert.IsType<ArcStatus>(f.Arc);
        Assert.Equal("Dinner & Drinks", arc.StageName);
        Assert.Equal(14390, arc.Remaining);
        Assert.True(arc.BaseBpm == 124 && arc.Manual.SequenceEqual(["smoke"]) && arc.Values["intensity"] == 0.565);
        Assert.True(f.Lite && f.Fx.Length == 0);
    }

    [Fact]
    public void OutdoorStageRoundTrips()
    {
        var st = Stage.From(JSONValue.Parse("""{"width_m": 12, "outdoor": true}""").ToJson().Let(b => J.ParseElement(b)));
        Assert.True(st.Outdoor);
        Assert.Equal(true, st.ToJSON()["outdoor"]?.Bool);
        var room = new Room(st, []);
        Assert.Equal(Room.Surface.Air, room.Hit(new(0, 0, 2), new(0, 0, 1)).Surface);  // straight up: no ceiling
    }

    [Fact]
    public void ARaisedStageRoundTripsAndBeamsLandOnIt()
    {
        var st = Stage.From(JSONValue.Parse("""{"width_m": 12, "deck_m": 1.5}""").ToJson().Let(b => J.ParseElement(b)));
        Assert.Equal(1.5, st.DeckM);
        Assert.Equal(1.5, st.ToJSON()["deck_m"]?.Number);
        Assert.Equal(0, Stage.From(JSONValue.Parse("""{"width_m": 12}""").ToJson().Let(b => J.ParseElement(b))).DeckM);
        var room = new Room(st, []);
        // straight down on the stage: on its deck, 1.5 m above the hall floor; in front of it: on the hall floor
        Assert.Equal(2.5f, room.Hit(new(6, -2, 4), new(0, 0, -1)).T, 4);
        Assert.Equal(Room.Surface.Floor, room.Hit(new(6, -2, 4), new(0, 0, -1)).Surface);
        Assert.Equal(4f, room.Hit(new(6, 2, 4), new(0, 0, -1)).T, 4);
        Assert.Equal(4f, new Room(new Stage(), []).Hit(new(6, -2, 4), new(0, 0, -1)).T, 4);
    }

    [Theory]
    [InlineData("small", 6)]
    [InlineData("laser-zones", 0)]
    [InlineData("ring", 0)]
    public void RealHellosDecode(string set, int expectFixtures)
    {
        var h = DecodeHello(Sample($"hello-{set}.json"));
        Assert.Equal("synthetic", h.Title);
        Assert.Equal(128, h.Bpm);
        Assert.Equal("rules", h.Director);
        Assert.NotEmpty(h.Fixtures);
        if (expectFixtures > 0) Assert.Equal(expectFixtures, h.Fixtures.Count);
        Assert.NotEmpty(h.Plan);
        Assert.Equal(400, h.Energy.Count);
        Assert.Equal(0, h.Plan[0].Phrase);
        Assert.Equal(h.Plan[0].Section, h.Plan[0]["section"]);
        Assert.Equal(1, h.PhraseIndex(h.Plan[1].Start + 0.01));
        Assert.Null(h.PhraseIndex(-1));
        foreach (var f in h.Fixtures) Assert.Equal(f.Id.Split('.')[0], f.Fixture);
    }

    [Fact]
    public void AHelloCarriesTheDrawingFacts()
    {
        var h = DecodeHello(Sample("hello-small.json"));
        var head = h.Fixtures.First(f => f.Id == "fuze1");
        Assert.Equal(FixtureKind.Head, head.Kind);
        Assert.Equal(new Vec3(0, 0, 1), head.Up);
        Assert.Null(head.Truss);
        Assert.Equal("moving_head", head.Body);
        var bar = h.Fixtures.First(f => f.Id == "compar1.1");
        Assert.Equal(4, bar.Cells);
        Assert.Equal(1.2, bar.Length);
        Assert.Equal(-5, bar.Rot);
        Assert.NotNull(bar.Dir);
    }

    [Fact]
    public void RealFramesDecode()
    {
        var f = DecodeFrame(Sample("frame-small.json"));
        Assert.Equal(100, f.T);
        Assert.Equal(3, f.Phrase);
        Assert.Equal(213.4, f.Bp);
        Assert.Equal(6, f.Fx.Length);
        Assert.All(f.Fx, x => Assert.Equal(7, x.Length));
        Assert.Equal("gobo_shake", f.Beam[0]);
        Assert.Null(f.Beam[2]);
        Assert.NotNull(f.Dirs[0]);
        Assert.Null(f.Dirs[2]);
        Assert.False(f.Lite);
        Assert.Null(f.Decks);

        var lasers = DecodeFrame(Sample("frame-laser-zones.json"));
        var drawn = lasers.Lz.Where(l => l is { Length: > 0 }).ToList();
        Assert.NotEmpty(drawn);
        Assert.All(drawn[0]!, b => Assert.InRange(b.Bright, 0, 1));
        var hello = DecodeHello(Sample("hello-laser-zones.json"));
        Assert.Equal(hello.Fixtures.Count, lasers.Fx.Length);
        Assert.Contains(hello.Zones, z => z.Kind == "laser_out" && z.Shape == "box");
    }

    [Fact]
    public void ALiveFrameCarriesTheDecksAndTheLink()
    {
        var json = """
            {"type": "frame", "lite": true, "t": 12.5, "phrase": 2, "bp": 24.5,
             "decks": [{"deck": 1, "track": "one", "vol": 0.8, "play": true, "ready": true,
                        "status": {"analysis": "done", "ai_done": 3, "ai_total": 9, "elapsed": 4}, "genre": "house", "style": "house"},
                       {"deck": 2, "track": "two", "vol": 0, "play": false, "ready": false, "status": {"missing": true}}],
             "link": {"name": "DJ laptop", "up": true, "offset_ms": 1.5, "jitter_ms": 0.4, "lost": 0, "packets": 120, "fetching": []},
             "guard": {"laser1": "zone 'Audience'"}, "fog": {"smoke1": 0.4}, "limit": 0.7}
            """;
        var f = DecodeFrame(json);
        Assert.Equal(2, f.Decks!.Count);
        Assert.Equal(3, f.Decks[0].Status!.AiDone);
        Assert.Null(f.Decks[1].Status!.Analysis);
        Assert.Equal("DJ laptop", f.Link!.Name);
        Assert.Equal("zone 'Audience'", f.LaserGuard!["laser1"]);
        Assert.Equal(0.4f, f.Fog["smoke1"]);
        Assert.Equal(f.Link, f.Link with { });  // equal by value (the feed only tells the UI when it changes)
    }

    [Fact]
    public void ToleratesWhatSwiftTolerates()
    {
        // missing fields take their defaults
        var h = DecodeHello("""{"type": "hello"}""");
        Assert.Equal(120, h.Bpm);
        Assert.Equal(6, h.Stage.WidthM);
        Assert.Empty(h.Fixtures);
        // the try? fields: wrong is left out, the message survives
        h = DecodeHello("""{"type": "hello", "trusses": "nonsense", "zones": [{"no": "id"}], "genre": 3}""");
        Assert.Empty(h.Trusses);
        Assert.Empty(h.Zones);
        Assert.Equal("", h.Genre);
        var f = DecodeFrame("""{"type": "frame", "arc": {"on": true}, "link": 3, "guard": [], "fog": {"x": "y"}}""");
        Assert.Null(f.Arc);
        Assert.Null(f.Link);
        Assert.Null(f.LaserGuard);
        Assert.Empty(f.Fog);
        // the strict fields: wrong fails the whole message, as JSONDecoder does
        Assert.Null(FeedMessage.Decode("""{"type": "hello", "bpm": "fast"}"""));
        Assert.Null(FeedMessage.Decode("""{"type": "frame", "decks": [{"deck": 1}]}"""));
        Assert.Null(FeedMessage.Decode("""{"type": "frame", "phrase": 2.5}"""));
        Assert.Null(FeedMessage.Decode("""{"type": "frame", "lite": 1}"""));
        Assert.Null(FeedMessage.Decode("""{"type": "hello", "fixtures": [{"id": "x"}]}"""));  // a fixture needs pos
        // an Int field takes a whole number written as a double
        Assert.Equal(2, DecodeFrame("""{"type": "frame", "phrase": 2.0}""").Phrase);
        // not ours
        Assert.Null(FeedMessage.Decode("""{"type": "other"}"""));
        Assert.Null(FeedMessage.Decode("""{"no": "type"}"""));
        Assert.Null(FeedMessage.Decode("not json"));
        Assert.Null(FeedMessage.Decode("[1, 2]"));
        // short direction vectors and laser beams are dropped, not fatal
        f = DecodeFrame("""{"type": "frame", "dirs": [[1, 0], null, [0, 1, 0]], "lz": [null, [[1, 2, 3], [0, 1, 0, 1, 1, 1, 0.5]]]}""");
        Assert.Equal([false, false, true], f.Dirs.Select(d => d.HasValue));
        Assert.Null(f.Lz[0]);
        Assert.Single(f.Lz[1]!);
    }

    [Fact]
    public void TitleDropsTheDeckAndTheExtension()
    {
        Assert.Equal("Track One", DecodeHello("""{"type": "hello", "track": "Deck A: Track One.mp3"}""").Title);
        Assert.Equal("live set", DecodeHello("""{"type": "hello", "track": "live set"}""").Title);
        Assert.Equal("v1.2 mix", DecodeHello("""{"type": "hello", "track": "Deck 2: v1.2 mix.flac"}""").Title);
    }

    [Fact]
    public void JSONValueTextAndEquality()
    {
        Assert.Equal("3", JSONValue.Of(3.0).Text);
        Assert.Equal("0.25", JSONValue.Of(0.25).Text);
        Assert.Equal("0.33", JSONValue.Of(1.0 / 3).Text);
        Assert.Equal("yes", JSONValue.True.Text);
        Assert.Equal("–", JSONValue.Null.Text);
        Assert.Equal("a, 2", JSONValue.Parse("""["a", 2]""").Text);
        Assert.Equal("…", JSONValue.Parse("{}").Text);
        Assert.Equal(JSONValue.Parse("""{"a": [1, {"b": null}]}"""), JSONValue.Parse("""{"a":[1.0,{"b":null}]}"""));
        Assert.NotEqual(JSONValue.Parse("""{"a": 1}"""), JSONValue.Parse("""{"a": true}"""));
        Assert.Equal("""{"a":1,"b":[0.5,"x/y"]}""", JSONValue.Parse("""{"b": [0.5, "x/y"], "a": 1.0}""").ToJson(sortKeys: true).Utf8());
    }

    [Fact]
    public void DecisionKeepsEveryField()
    {
        var d = Decision.From(J.ParseElement(Encoding.UTF8.GetBytes("""
            {"phrase": 4, "start": 1, "end": 9, "section": "drop", "movement": "sweep", "confidence": {"section": 0.9, "x": "no"},
             "probabilities": {"palette": {"warm": 0.7}}, "intensity": 3}
            """)));
        Assert.Equal(4, d.Id);
        Assert.Equal("sweep", d["movement"]);
        Assert.Equal("–", d["missing"]);
        Assert.Equal("cool", d.Palette);
        Assert.Equal(0.9, d.Confidence["section"]);
        Assert.False(d.Confidence.ContainsKey("x"));
        Assert.Equal(0.7, d.Probabilities["palette"]["warm"]);
    }

    [Fact]
    public void TheLightTestSaysWhereAPointedHeadsBeamGoes()
    {
        static LightTest Decode(string json) => LightTest.From(J.ParseElement(Encoding.UTF8.GetBytes(json)));
        var lit = Decode("""
            {"on": true, "seconds": 60, "output": "Art-Net", "universe": 1, "wire_universe": 0, "channels": [43, 50], "dir": [0.0, -0.966, -0.259]}
            """);
        Assert.Equal(new System.Numerics.Vector3(0, -0.966f, -0.259f), lit.Dir);
        Assert.Equal("universe 1, channels 43–50 · Art-Net (universe 0 on the wire)", lit.Summary);
        // switched off, a fixture without an address, not a head: null channels and no dir
        var off = Decode("""{"on": false, "seconds": 60, "output": "Art-Net", "universe": 1, "channels": null, "dir": null}""");
        Assert.Empty(off.Channels);
        Assert.Null(off.Dir);
        Assert.Null(Decode("""{"on": true, "seconds": 60, "output": "", "universe": 1, "dir": [1, 2]}""").Dir);  // too short
    }

    [Fact]
    public void AStillFrameFromTheAppLightsAndPoints()
    {
        var f = new Frame([[1, 1, 1, 1, 0, 0.5f, 0.5f], [0, 0, 0, 0, 0, 0.5f, 0.5f]], [new System.Numerics.Vector3(0, -1, 0), null]);
        Assert.Equal(2, f.Fx.Length);
        Assert.Equal("open", f.Beam[0]);
        Assert.Null(f.Beam[1]);
        Assert.Equal(new System.Numerics.Vector3(0, -1, 0), f.Dirs[0]);
        Assert.Null(f.Dirs[1]);
        Assert.Equal(2, f.Lz.Length);
        Assert.All(f.Lz, Assert.Null);
        Assert.False(f.Lite);
        Assert.Empty(f.Bands);
        Assert.Empty(f.Gobo);
        Assert.Empty(f.Zoom);
        Assert.Empty(f.Ring);
    }

    // the hello's gobo pictures and a frame's gobo and zoom, in the format of docs/protocols.md
    [Fact]
    public void AHelloCarriesTheGoboPictures()
    {
        var h = DecodeHello("""
            {"type": "hello", "track": "Deck 1: track.mp3", "fixtures": [],
             "gobos": [{"key": "qlc/ClayPaky/gobo00006", "img": "iVBORw0KGgo=", "style": "rings"},
                       {"key": "ofl/robe/glass-1", "img": "/9j/4AAQ", "style": "figure"}]}
            """);
        Assert.Equal(2, h.Gobos.Count);
        Assert.Equal(new GoboPicture { Key = "qlc/ClayPaky/gobo00006", Img = "iVBORw0KGgo=", Style = "rings" }, h.Gobos[0]);
        Assert.Equal("figure", h.Gobos[1].Style);
        // none sent, or not readable: no pictures, the hello survives
        Assert.Empty(DecodeHello("""{"type": "hello"}""").Gobos);
        Assert.Empty(DecodeHello("""{"type": "hello", "gobos": [{"key": "x"}]}""").Gobos);
    }

    [Fact]
    public void AFrameCarriesEachHeadsGoboAndZoom()
    {
        var f = DecodeFrame("""
            {"type": "frame", "t": 1.0, "phrase": 0, "fx": [[1,1,1,1,0,0.5,0.5],[1,1,1,1,0,0.5,0.5],[1,0,0,0,0,0,0]],
             "beam": ["gobo", "open", null],
             "gobo": [[3, 4, 0.25, -0.5, 2.0, 1], null, null],
             "zoom": [0.0, 0.75, null]}
            """);
        Assert.Equal(3, f.Gobo.Length);
        Assert.Equal(new GoboState(3, 4, 0.25f, -0.5f, 2.0f, true), f.Gobo[0]);
        Assert.Null(f.Gobo[1]);
        Assert.Null(f.Gobo[2]);
        Assert.Equal(new float?[] { 0f, 0.75f, null }, f.Zoom);
        // the open hole and no prism
        var open = DecodeFrame("""{"type": "frame", "gobo": [[-1, 2, 0.5, 0, 0, 0]]}""");
        Assert.Equal(new GoboState(-1, 2, 0.5f), open.Gobo[0]);
        Assert.False(open.Gobo[0]!.Value.Prism);
        // too short is null; not sent is empty; the wrong type drops the field, not the frame
        Assert.Null(DecodeFrame("""{"type": "frame", "gobo": [[1, 2, 0.5]]}""").Gobo[0]);
        var none = DecodeFrame("""{"type": "frame"}""");
        Assert.Empty(none.Gobo);
        Assert.Empty(none.Zoom);
        var bad = DecodeFrame("""{"type": "frame", "gobo": [["a", 1, 0, 0, 0, 0]], "zoom": ["wide"]}""");
        Assert.Empty(bad.Gobo);
        Assert.Empty(bad.Zoom);
    }

    [Fact]
    public void AHeadsRingColourDecodesPerElement()
    {
        var f = DecodeFrame("""
            {"type": "frame", "t": 1, "phrase": 0, "fx": [[1, 1, 0, 0, 0, 0.5, 0.5], [0, 0, 0, 0, 0, 0.5, 0.5]],
             "ring": [[1, 0, 0], null]}
            """);
        Assert.Equal(2, f.Ring.Length);
        Assert.Equal(new System.Numerics.Vector3(1, 0, 0), f.Ring[0]);
        Assert.Null(f.Ring[1]);
        Assert.Empty(DecodeFrame("""{"type": "frame", "t": 1, "phrase": 0}""").Ring);  // an engine without rings
    }

    [Fact]
    public void AHeadsFluxAndFieldDecodeAndDrawAsBeamLight()
    {
        var h = DecodeHello("""
            {"type": "hello", "fixtures": [{"id": "a", "kind": "head", "pos": [1, 0, 3], "beam_deg": 4, "flux": 1.6, "field": 1.5},
                                           {"id": "b", "kind": "head", "pos": [2, 0, 3], "beam_deg": 4}]}
            """);
        Assert.Equal(1.6, h.Fixtures[0].Flux);
        Assert.Equal(1.5, h.Fixtures[0].Field);
        Assert.Equal(1, h.Fixtures[1].Flux);                    // an older engine: the reference light, a smooth lens
        Assert.Equal(BeamLight.Field, h.Fixtures[1].Field);
        // the reference beam (4° at 4 m) has gain 1; a narrower one is brighter (at most 3), a wider one dimmer
        Assert.Equal(1, BeamLight.Gain(4 * MathF.Tan(2 * MathF.PI / 180)), 4);
        Assert.Equal(BeamLight.MaxGain, BeamLight.Gain(0.001f));
        Assert.True(BeamLight.Gain(1) < 0.2f);
        Assert.Equal(7.2f, BeamLight.FieldDeg(4, 1.8f), 4);
        Assert.Equal(70, BeamLight.FieldDeg(40, 1.8f));         // a wide wash's glow at most 30° wider
        Assert.Equal(1, BeamLight.Flux(1500));
        Assert.Equal(1, BeamLight.Flux(null));
        Assert.Equal(0.25, BeamLight.Flux(10));
        Assert.Equal(2.5, BeamLight.Flux(1e6));
    }
}

static class TestHelpers
{
    public static TOut Let<TIn, TOut>(this TIn x, Func<TIn, TOut> f) => f(x);
    public static string Utf8(this byte[] b) => Encoding.UTF8.GetString(b);
}
