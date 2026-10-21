// The DMX mapper's check, channel by channel: what the others hold while one sweeps, and what an answer makes a
// channel. The description is the engine's (amadeus/library/mapper.py describe) for a fixture made from a layout
// (mac/Tests/AmadeusKitTests/ChannelCheckTests.swift).
namespace AmadeusKit.Tests;

public class ChannelCheckTests
{
    static FixtureMapping Mapping() => J.DecodeOrThrow(J.Utf8("""
        {"key":"chegit/spot","name":"Chegit Spot","mode":"9ch","kind":"moving_head","kinds":{"par":"Par / wash / effect","moving_head":"Moving head"},
         "roles":[{"role":"dimmer","label":"Dimmer","group":"Intensity","cell":true,"light":true,"check":255},
                  {"role":"color_wheel","label":"Colour wheel","group":"Colour","cell":false,"light":false,"check":0},
                  {"role":"pan","label":"Pan","group":"Position","cell":false,"light":false,"check":128},
                  {"role":"tilt","label":"Tilt","group":"Position","cell":false,"light":false,"check":128}],
         "channels":[{"n":1,"attr":"pan","role":"pan","cell":0,"value":0,"name":"Pan","ranges":[]},
                     {"n":2,"attr":"tilt","role":"tilt","cell":0,"value":0,"name":"Tilt","ranges":[]},
                     {"n":3,"attr":"color_wheel","role":"color_wheel","cell":0,"value":0,"name":"Colour wheel","ranges":[[0,9,"open / white"]]},
                     {"n":4,"attr":"gobo","role":"hold","cell":0,"value":5,"name":"Gobo","ranges":[]},
                     {"n":5,"attr":"dimmer","role":"dimmer","cell":0,"value":0,"name":"Dimmer","ranges":[]}],
         "plays":true,"mapped":false,"refusal":"","made":true,"checked":false,
         "check":[{"answer":"Turns left and right","role":"pan"},{"answer":"Tilts up and down","role":"tilt"},
                  {"answer":"Gobos change","role":"hold","attr":"gobo","value":0},{"answer":"Nothing I can see","role":"hold","value":0}],
         "wheel":[{"name":"open","from":0,"to":15,"rgb":[1.0,1.0,1.0]},{"name":"red","from":16,"to":31,"rgb":[1.0,0.0,0.0]}]}
        """), FixtureMapping.From);

    [Fact]
    public void TheOthersKeepTheLightOnWhileOneSweeps()
    {
        var m = Mapping();
        Assert.True(m.Made && !m.Checked && m.Wheel.Count == 2);
        Assert.Equal([128, 128, 77, 5, 255], m.CheckValues(2, 77));  // head centred, gobo held, dimmer up
        Assert.Equal([4], m.LightChannels);
        Assert.True(new MapperModel { Mapping = m }.NeedsCheck);
    }

    [Fact]
    public void AnAnswerMakesTheChannel()
    {
        var m = new MapperModel { Mapping = Mapping() };
        m.Answer(m.Mapping!.Check[1], 0);  // channel 1 tilts: the manual had pan and tilt swapped
        Assert.Equal("tilt", m.Mapping!.Channels[0].Role);
        m.Answer(m.Mapping.Check[2], 2);  // channel 3 is the gobo wheel
        Assert.True(m.Mapping.Channels[2] is { Role: "hold", Attr: "gobo", Value: 0 });
        m.Answer(m.Mapping.Check[3], 3);  // channel 4 does nothing: not the gobo any more
        Assert.True(m.Mapping.Channels[3] is { Role: "hold", Attr: "channel_4" });
    }

    [Fact]
    public void AColourWheelGetsTheUsualSlotsUntilNamed()
    {
        var m = Mapping() with { Wheel = [] };
        var a = new FixtureMapping.Answer("Colours change", "color_wheel", null, null);
        var w = m.Answered(a, 3).Wheel;
        Assert.Equal(8, w.Count);
        Assert.Equal(("orange", 112, 127), (w[7].Name, w[7].From, w[7].To));
        Assert.Equal(0, m.Answered(a, 3).Channels[3].Cell);
    }

    [Fact]
    public void AnOlderEngineWithoutTheCheckStillDecodes()
    {
        var m = J.DecodeOrThrow(J.Utf8("""
            {"key":"k","name":"n","mode":"m","kind":"par","kinds":{},"roles":[{"role":"dimmer","label":"Dimmer","group":"Intensity","cell":true}],
             "channels":[],"plays":false,"mapped":false,"refusal":""}
            """), FixtureMapping.From);
        Assert.True(!m.Made && m.Checked && m.Check.Count == 0 && m.Roles[0].Check is null);
    }

    [Fact]
    public void ADefinitionMadeFromALayoutWantsTheCheck()
    {
        FixtureDefinition D(string made) => J.DecodeOrThrow(J.Utf8($$"""{"manufacturer":"x","model":"y","modes":{}{{made}}}"""), FixtureDefinition.From);
        Assert.True(D(""","made":{"template":"spot9","checked":false}""").NeedsCheck);
        Assert.True(D(""","made":{}""").NeedsCheck);
        Assert.False(D(""","made":{"checked":true}""").NeedsCheck);
        Assert.False(D("").NeedsCheck);
        Assert.False(D(""","made":true""").NeedsCheck);
    }
}
