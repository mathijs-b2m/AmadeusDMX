// The DMX mapper's check, channel by channel on the real fixture: one channel sweeps slowly from 0 to 255 while
// the others keep the light on and the head in the middle, and you say what the fixture does. That puts right what
// the manual (or the layout a fixture was made from) has wrong; a colour wheel's (or LED ring's) colours are named on
// the way, or on their own from the mapper's Colours… (ColourWheelEditor) (mac/Sources/AmadeusDMX/Sets/ChannelCheck.swift).
using System.Numerics;

namespace AmadeusDMX;

/// What the check is at (Swift's bindings): the channel checked, the value it gets now, sweeping or held there.
public sealed class ChannelCheckState : Observable
{
    int _index, _probe;
    bool _sweeping = true;
    public int Index { get => _index; set => Set(ref _index, value); }
    public int Probe { get => _probe; set => Set(ref _probe, Math.Clamp(value, 0, 255)); }
    public bool Sweeping { get => _sweeping; set => Set(ref _sweeping, value); }
}

public sealed class ChannelCheck(MapperModel m, ChannelCheckState s, Action finish)
{
    readonly ContentControl _host = new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };

    FixtureMapping Mapping => m.Mapping!;
    FixtureMapping.Channel Channel => Mapping.Channels[s.Index];
    bool Last => s.Index == Mapping.Channels.Count - 1;

    public FrameworkElement Build()
    {
        Rebuild();
        return _host;
    }

    void Rebuild() => _host.Rebuild(Body);

    UIElement Body()
    {
        var ch = Channel;
        var answers = new FlowPanel { Spacing = 8, LineSpacing = 8 };
        foreach (var a in Mapping.Check)
        {
            var on = Chosen(a);
            var b = new Button
            {
                Content = UI.HStack(6, UI.Text(a.AnswerText).Grow(), on ? UI.Icon("checkmark", 12).Foreground(Tint.Accent) : null),
                Width = 190, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            };
            if (on) b.BorderBrush = new Microsoft.UI.Xaml.Media.SolidColorBrush(Tint.Accent);
            b.Click += (_, _) => Pick(a);
            answers.Children.Add(b);
        }

        return UI.Scroll(UI.VStack(14,
            UI.HStack(8,
                UI.Text($"Channel {ch.N} of {Mapping.Channels.Count}", Font.Title3).Bold(),
                UI.Text($"now: {Now}").Secondary(),
                UI.Spacer()),
            UI.Text("Watch the fixture: this channel sweeps slowly from 0 to 255, the others keep the light on and the head in the middle. What does it do?")
                .Secondary().Wrap(),
            Probing(s),
            answers,
            ch.Role == "hold" ? Hold(ch) : null,
            ch.Role == "color_wheel" ? new WheelNaming(m, s).Build() : null,
            ch.Role == "ring_color" ? new WheelNaming(m, s, ring: true).Build() : null,
            UI.HStack(8,
                UI.Button("Previous", () => Go(s.Index - 1), "chevron.left").Disabled(s.Index == 0),
                UI.Spacer(),
                Last ? UI.Button("Finish Check", finish).Prominent()
                     : UI.Button("Next Channel", () => Go(s.Index + 1), "chevron.right").Prominent())
        ).Padding(16));
    }

    /// Sweep (or not) and the value the probed channel gets now.
    internal static UIElement Probing(ChannelCheckState s)
    {
        var sweep = Form.ToggleButton(UI.Label(s.Sweeping ? "pause.fill" : "play.fill", s.Sweeping ? "Sweeping" : "Sweep"), s.Sweeping, on => s.Sweeping = on)
            .Bind(s, nameof(ChannelCheckState.Sweeping), b =>
            {
                b.IsChecked = s.Sweeping;
                b.Content = UI.Label(s.Sweeping ? "pause.fill" : "play.fill", s.Sweeping ? "Sweeping" : "Sweep");
            });
        var probe = UI.Slider(s.Probe, 0, 255, v => { s.Probe = (int)Math.Round(v); s.Sweeping = false; }, step: 1)
            .Bind(s, nameof(ChannelCheckState.Probe), sl => sl.SetValueQuietly(s.Probe));
        var value = UI.Text($"{s.Probe}", Font.Mono).Frame(width: 34)
            .Bind(s, nameof(ChannelCheckState.Probe), t => t.Text = $"{s.Probe}");
        value.TextAlignment = TextAlignment.Right;
        return UI.HStack(8, sweep, probe.Grow(), value);
    }

    /// A held channel: its value, where the light is on and steady.
    UIElement Hold(FixtureMapping.Channel ch)
    {
        var text = UI.Text($"{ch.Value}", Font.Mono).Frame(width: 34);
        text.TextAlignment = TextAlignment.Right;
        var slider = UI.Slider(ch.Value, 0, 255, v =>
        {
            var x = (int)Math.Round(v);
            m.SetValue(s.Index, x);
            s.Sweeping = false;
            s.Probe = x;
            text.Text = $"{x}";
        }, step: 1);
        return UI.VStack(4,
            UI.Text("Held at a value: set it where the light is on and steady (no strobe, no programs)", Font.Callout).Wrap(),
            UI.HStack(8, slider.Grow(), text),
            ch.Ranges.Count == 0 ? null
                : UI.Text(string.Join(" · ", ch.Ranges.Select(r => $"{r.Lo}–{r.Hi} {r.What}")), Font.Caption).Secondary().Wrap());
    }

    /// What the channel is now, in words.
    string Now
    {
        get
        {
            var ch = Channel;
            if (ch.Role == "hold") return $"held at {ch.Value} ({ch.Attr.Replace('_', ' ')})";
            return Mapping.Roles.FirstOrDefault(r => r.RoleName == ch.Role)?.Label ?? ch.Role;
        }
    }

    bool Chosen(FixtureMapping.Answer a)
    {
        var ch = Channel;
        if (a.Role != "hold") return ch.Role == a.Role;
        if (ch.Role != "hold") return false;
        if (a.Attr is { } attr) return ch.Attr == attr;
        return !Mapping.Check.Any(x => x.Attr == ch.Attr);  // "nothing": held, and none of the named ones
    }

    void Pick(FixtureMapping.Answer a)
    {
        m.Answer(a, s.Index);
        if (a.Role == "hold") { s.Sweeping = false; s.Probe = Channel.Value; }  // held there from now on
        Rebuild();
    }

    void Go(int i)
    {
        if (i < 0 || i >= Mapping.Channels.Count) return;
        s.Index = i;
        s.Probe = 0;
        s.Sweeping = true;
        Rebuild();
    }
}

/// The mapper's Colours…: the colour wheel's (or the ring's) colours named and their values put right, without the
/// whole check. `s.Index` is not used: the wheel's channel is `index`.
public sealed class ColourWheelEditor(MapperModel m, int index, ChannelCheckState s, Action done)
{
    bool Ring => m.IsRing(index);

    public FrameworkElement Build() => UI.Scroll(UI.VStack(14,
        UI.HStack(8,
            UI.Text(Ring ? "Ring Colour" : "Colour Wheel", Font.Title3).Bold(),
            UI.Text($"channel {m.Mapping!.Channels[index].N}").Secondary(),
            UI.Spacer(),
            UI.Button("Done", done).Prominent()),
        UI.Text(Ring ? "The light is on and the head in the middle. Show each colour of the ring round the lens, say what you see, and set its values. Name the one where the ring is off \"off\": the ring rests with the head. Sweep goes through the whole channel."
                     : "The light is on and the head in the middle. Show each colour, say what you see, and set its values where the colour is whole (not between two). Sweep goes through the whole wheel.")
            .Secondary().Wrap(),
        ChannelCheck.Probing(s),
        new WheelNaming(m, s, Ring).Build()
    ).Padding(16));
}

/// The colour wheel's (or a ring's) colours: show each on the fixture, say what it is, put its values right.
/// `ring`: a ring round the lens: "off" and "white" instead of the wheel's "open".
sealed class WheelNaming(MapperModel m, ChannelCheckState s, bool ring = false)
{
    static readonly (string Name, double[] Rgb)[] Colours =
    [
        ("open", [1, 1, 1]), ("red", [1, 0, 0]), ("orange", [1, 0.45, 0]), ("yellow", [1, 0.9, 0]),
        ("green", [0, 1, 0]), ("cyan", [0, 0.9, 1]), ("light blue", [0.4, 0.7, 1]), ("blue", [0, 0.2, 1]),
        ("purple", [0.5, 0, 1]), ("magenta", [1, 0, 0.8]), ("pink", [1, 0.4, 0.7]), ("uv", [0.35, 0, 1]),
        ("warm white", [1, 0.8, 0.55]),
    ];

    (string Name, double[] Rgb)[] Choices =>
        ring ? [("off", [0, 0, 0]), ("white", [1, 1, 1]), .. Colours.Skip(1)] : Colours;

    readonly ContentControl _host = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    IReadOnlyList<FixtureMapping.Slot> Slots => m.Slots(ring);

    public FrameworkElement Build()
    {
        _host.Rebuild(Body);
        return _host;
    }

    UIElement Body()
    {
        var rows = UI.VStack(6,
            UI.Text("Name the colours: show each, say what you see, and set its values where the colour is whole", Font.Callout).Wrap());
        for (var i = 0; i < Slots.Count; i++) rows.Children.Add(Row(i));
        var add = UI.Button("Add a Colour", () =>
        {
            var from = Math.Min((Slots.Count > 0 ? Slots[^1].To : -1) + 1, 255);
            m.SetWheel([.. Slots, new FixtureMapping.Slot("red", from, Math.Min(from + 15, 255), [1, 0, 0])], ring);
            _host.Rebuild(Body);
        }, "plus");
        rows.Children.Add(add);
        return UI.Card(rows, padding: 10, corner: 8);
    }

    UIElement Row(int i)
    {
        var slot = Slots[i];
        var show = UI.Button("Show", () => { s.Sweeping = false; s.Probe = Slots[i].Mid; })
            .Bind(s, [nameof(ChannelCheckState.Probe), nameof(ChannelCheckState.Sweeping)], b =>
            {
                var on = i < Slots.Count && s.Probe >= Slots[i].From && s.Probe <= Slots[i].To && !s.Sweeping;
                b.BorderBrush = on ? new Microsoft.UI.Xaml.Media.SolidColorBrush(Tint.Accent) : null;
            });
        TextBox Number(int v, Func<FixtureMapping.Slot, int, FixtureMapping.Slot> set)
        {
            var t = new TextBox { Text = v.ToString(System.Globalization.CultureInfo.InvariantCulture), Width = 52, TextAlignment = TextAlignment.Right };
            t.TextChanged += (_, _) =>
            {
                if (int.TryParse(t.Text, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var x))
                    m.SetSlot(i, sl => set(sl, Math.Clamp(x, 0, 255)), ring);
            };
            return t;
        }
        var swatch = new Microsoft.UI.Xaml.Shapes.Ellipse
        {
            Width = 14, Height = 14, VerticalAlignment = VerticalAlignment.Center,
            Fill = new Microsoft.UI.Xaml.Media.SolidColorBrush(Tint.From(Rgb(slot.Rgb))),
            Stroke = Theme.Brush("TextFillColorSecondaryBrush"), StrokeThickness = 1,
        };
        var names = Choices.Select(c => c.Name).ToList();
        if (!names.Contains(slot.Name)) names.Insert(0, slot.Name);
        var picker = UI.Picker(names, slot.Name, n => n, n =>
        {
            var known = Choices.Where(c => c.Name == n).Select(c => c.Rgb).FirstOrDefault();
            m.SetSlot(i, sl => sl with { Name = n, Rgb = known ?? sl.Rgb }, ring);
            _host.Rebuild(Body);
        }).Frame(width: 130);
        var remove = UI.IconButton("minus.circle", "Remove", () =>
        {
            var list = Slots.ToList();
            if (list.Count <= 1 || i >= list.Count) return;
            list.RemoveAt(i);
            m.SetWheel(list, ring);
            _host.Rebuild(Body);
        }).Disabled(Slots.Count <= 1);
        return UI.HStack(8, show, Number(slot.From, (sl, x) => sl with { From = x }), UI.Text("–"),
                         Number(slot.To, (sl, x) => sl with { To = x }), swatch, picker, remove);
    }

    static Vector3 Rgb(IReadOnlyList<double> c) =>
        c.Count >= 3 ? new Vector3((float)c[0], (float)c[1], (float)c[2]) : Vector3.One;
}
