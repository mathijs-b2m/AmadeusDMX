// The night (the show arc, live mode): the countdown, the stage the music is in, and the knobs the arc turns
// over the night. Any knob can be taken over (it then stays where you put it) and given back (Auto).
// The engine does the work (amadeus/show/arc.py); this card only shows it and sends what you change.
//
// The arc comes with every feed update (5 times a second): the card is built again only when its shape changes
// (opened, the arc switched on or off, other stages or events); everything else moves in place, so a slider
// being dragged or a menu being open is never pulled away.
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;

namespace AmadeusDMX;

public sealed class NightCard(AppModel model)
{
    bool _open = Defaults.Standard.Bool("nightCardOpen");
    string? _shape;
    readonly List<Action<ArcStatus>> _updates = [];
    readonly Stack _body = UI.VStack(10);
    Border? _card;

    // the header
    readonly FontIcon _moon = UI.Icon("moon.stars").Secondary();
    readonly TextBlock _title = UI.Text("", Font.Headline);
    readonly FontIcon _pin = UI.Icon("pin.fill", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
    readonly FontIcon _hand = UI.Icon("hand.raised.fill", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
    readonly TextBlock _clock = UI.Text("", Font.Caption).Secondary();
    readonly TextBlock _countdown = UI.Text("", Font.Title2).Bold();
    readonly FontIcon _chevron = UI.Icon("chevron.down").Secondary();

    ArcStatus? Arc => model.Feed.Arc;

    void Send(Dictionary<string, object> message) => model.Feed.Send(message);

    public FrameworkElement Build()
    {
        var header = new Button
        {
            Content = UI.HStack(10,
                _moon,
                UI.VStack(1, UI.HStack(5, _title, _pin, _hand).Leading(), _clock.Leading()),
                UI.Spacer(8),
                _countdown,
                _chevron),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
        }.Borderless().Tooltip("The night: its stage, countdown and the knobs the show arc turns");
        header.Padding = new Thickness(0);
        header.Click += (_, _) =>
        {
            _open = !_open;
            Defaults.Standard.Set("nightCardOpen", _open);
            Refresh();
        };
        _chevron.RenderTransformOrigin = new Windows.Foundation.Point(0.5, 0.5);
        _card = ShowUI.Glass(UI.VStack(10, header, _body));
        return _card.Bind(model.Feed, nameof(LiveFeed.Arc), _ => Refresh());
    }

    void Refresh()
    {
        if (Arc is not { } arc || _card is null) return;
        var shape = $"{_open}|{arc.On}|{string.Join(",", arc.Stages.Select(s => string.Join("=", s)))}|{string.Join(",", arc.Events.Select(e => string.Join("=", e)))}";
        if (shape != _shape)
        {
            _shape = shape;
            BuildBody(arc);
            _card.Width = _open ? 340 : double.NaN;
            _chevron.RenderTransform = new RotateTransform { Angle = _open ? 180 : 0 };
        }
        UpdateHeader(arc);
        foreach (var u in _updates) u(arc);
    }

    void UpdateHeader(ArcStatus arc)
    {
        _moon.Glyph = Symbols.Glyph(arc.On ? "moon.stars" : "moon.zzz");
        _title.Text = Night.Title(arc);
        _pin.Visible(arc.Locked);
        _hand.Visible(arc.Manual.Count > 0).Tooltip(Night.HeldHelp(arc));
        _clock.Text = Night.Clock(arc);
        var left = Night.Countdown(arc);
        _countdown.Visible(left is not null);
        _countdown.Text = left ?? "";
        _countdown.Foreground = Night.Over(arc) ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorPrimaryBrush");
        _countdown.Tooltip(Night.Over(arc) ? "Over the night's length" : "Left of the night");
    }

    void BuildBody(ArcStatus arc)
    {
        _body.Children.Clear();
        _updates.Clear();
        _body.Visible(_open);
        if (!_open) return;
        _body.Children.Add(UI.Divider());
        if (arc.On)
        {
            _body.Children.Add(StageStrip(arc));
            _body.Children.Add(HeatRow());
            _body.Children.Add(UI.Divider());
            foreach (var (title, knobs) in Knob.Sections)
            {
                _body.Children.Add(UI.Text(title.ToUpperInvariant(), Font.Caption2).Bold().Secondary().Margin(0, 2, 0, 0).Leading());
                foreach (var k in knobs) _body.Children.Add(KnobRow(k));
            }
            _body.Children.Add(UI.Divider());
        }
        _body.Children.Add(NightSettings(arc));
    }

    // MARK: a knob

    UIElement KnobRow(Knob knob)
    {
        var draft = new KnobDraft();
        var value = UI.Text("", Font.Caption).Secondary().Frame(width: 34);
        value.TextAlignment = TextAlignment.Right;
        var auto = UI.Button("Auto", () => Send(ArcMessage.Auto(knob.Id))).Borderless().Font(Font.Caption);
        FrameworkElement control;
        if (knob.Toggle)
        {
            var toggle = UI.Toggle("", Night.KnobLevel(knob, Arc!) >= 0.5, on => Send(ArcMessage.Knob(knob.Id, on ? 1.0 : 0.0)));
            control = UI.HStack(toggle, UI.Spacer()).Grow();
            _updates.Add(arc => toggle.SetOn(Night.KnobLevel(knob, arc) >= 0.5));
        }
        else
        {
            var slider = UI.Slider(Night.KnobLevel(knob, Arc!), 0, 1, v =>
            {
                draft.Move(v);
                if (Arc is { } a) value.Text = Night.KnobValue(knob, a, v);
                Send(ArcMessage.Knob(knob.Id, v));
            });
            // the drag ended: the arc's value counts again (Swift's onEditingChanged)
            var ended = new PointerEventHandler((_, _) => draft.End());
            slider.AddHandler(UIElement.PointerCaptureLostEvent, ended, true);
            slider.AddHandler(UIElement.PointerReleasedEvent, ended, true);
            slider.LostFocus += (_, _) => draft.End();
            control = slider.Grow();
            _updates.Add(arc =>
            {
                var v = draft.Shown(Night.KnobLevel(knob, arc));
                if (draft.Draft is null) slider.SetValueQuietly(v);
                value.Text = Night.KnobValue(knob, arc, v);
            });
        }
        var row = UI.HStack(8,
            UI.Icon(knob.Symbol).Secondary().Frame(width: 18),
            UI.Text(knob.Title, Font.Callout).Lines(1).Frame(width: 110),
            control,
            knob.Toggle ? null : value,
            auto);
        _updates.Add(arc =>
        {
            var manual = arc.Manual.Contains(knob.Id);
            auto.IsEnabled = manual;
            auto.FontWeight = manual ? FontWeights.Normal : FontWeights.SemiBold;
            auto.Foreground = manual ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Accent);
            auto.Tooltip(manual ? "Give this knob back to the show arc" : "The show arc turns this knob");
            row.Tooltip(Night.KnobHelp(knob, arc));
        });
        return row;
    }

    // MARK: the stages, named for the event: the one the music is in lit; click one to force it

    UIElement StageStrip(ArcStatus arc)
    {
        var strip = UI.HStack(4);
        foreach (var s in arc.Stages)
        {
            var key = s.Count > 0 ? s[0] : "";
            var label = UI.Text(s.Count > 0 ? s[^1] : key, Font.Caption2).Center().Wrap(2);
            var b = new Button
            {
                Content = label,
                MinHeight = 30,
                Padding = new Thickness(4, 2, 4, 2),
                BorderThickness = new Thickness(0),
                CornerRadius = new CornerRadius(6),
                HorizontalAlignment = HorizontalAlignment.Stretch,
                VerticalAlignment = VerticalAlignment.Stretch,
            };
            b.Click += (_, _) => Send(ArcMessage.Stage(key));
            strip.Children.Add(b.Grow().Fill());
            _updates.Add(a =>
            {
                var now = key == a.Stage;
                label.FontWeight = now ? FontWeights.Bold : FontWeights.Normal;
                b.Background = now ? Tint.Brush(Tint.Accent, 0.35) : ShowUI.Brush(Tone.Secondary, 0.12);
                b.Tooltip(now ? "The music is here" : "Go to this stage now (the arc carries on from there)");
            });
        }
        var held = UI.Text("", Font.Caption).Secondary();
        var hold = new ToggleButton { Content = "Hold" }.Small().Tooltip("Keep the night in this stage until you let go");
        hold.Click += (_, _) => Send(ArcMessage.Lock(hold.IsChecked == true));
        _updates.Add(a =>
        {
            held.Text = a.Locked ? "Held: the arc stays in this stage" : "The music decides the stage";
            hold.IsChecked = a.Locked;
        });
        return UI.VStack(6, strip, UI.HStack(held, UI.Spacer(), hold));
    }

    // MARK: how hot the mix runs (what the stages are detected from)

    UIElement HeatRow()
    {
        var heat = UI.Progress(0);
        heat.Foreground = Tint.Brush(Tint.Orange);
        var trend = UI.Icon("arrow.right", Theme.Size(Font.Caption)).Secondary();
        var bpm = UI.Text("", Font.Caption).Secondary();
        var row = UI.HStack(8,
            UI.Icon("thermometer.medium").Secondary().Frame(width: 18),
            UI.Text("Music heat", Font.Callout).Frame(width: 110),
            heat.Grow(),
            trend,
            bpm);
        _updates.Add(a =>
        {
            heat.Value = Math.Clamp(a.Heat, 0, 1);
            trend.Glyph = Symbols.Glyph(Night.HeatSymbol(a));
            bpm.Visible(a.Bpm is not null);
            bpm.Text = a.Bpm is { } b ? $"{Num.Round(b)}" : "";
            row.Tooltip(Night.HeatHelp(a));
        });
        return row;
    }

    // MARK: the event type, the night's length, on/off and a new night

    UIElement NightSettings(ArcStatus arc)
    {
        var events = arc.Events.Select(e => (Key: e.Count > 0 ? e[0] : "", Title: e.Count > 0 ? e[^1] : "")).ToList();
        var picker = UI.Picker(events, events.FirstOrDefault(e => e.Key == arc.Event), e => e.Title, e => Send(ArcMessage.Event(e.Key)));
        var eventRow = UI.HStack(8, UI.Text("Event", Font.Callout), picker.Grow())
            .Tooltip("What kind of night: it names the stages, sets where in the night they may come, and the character (a wedding: fewer lasers, less smoke)");

        var length = UI.Text("", Font.Body).Frame(width: 48);
        length.TextAlignment = TextAlignment.Center;
        var minus = UI.IconButton("minus", "", () => { if (Arc is { } a) Send(ArcMessage.Length(a.Length - Night.Step)); }).Borderless();
        var plus = UI.IconButton("plus", "", () => { if (Arc is { } a) Send(ArcMessage.Length(a.Length + Night.Step)); }).Borderless();
        var lengthRow = UI.HStack(8, UI.Text("Length", Font.Callout), UI.Spacer(), minus, length, plus)
            .Tooltip("How long the night is: the countdown, and where the warm-up and the finale belong (a quarter of an hour per click)");

        var on = UI.Check("Show arc", arc.On, v => Send(ArcMessage.Enabled(v))).Tooltip("Off: the lights play every track as the director made it, at full");
        var allAuto = UI.Button("All Auto", () => Send(ArcMessage.Auto("all"))).Small();
        var newNight = UI.Button("New Night", () => Send(ArcMessage.Reset())).Small()
            .Tooltip("Start again: the clock waits for the music, the night begins with the warm-up");
        var onRow = UI.HStack(8, on, UI.Spacer(), allAuto, newNight);

        _updates.Add(a =>
        {
            picker.Select(events.FirstOrDefault(e => e.Key == a.Event));
            length.Text = Night.Hm(a.Length);
            minus.IsEnabled = Night.CanShorten(a);
            plus.IsEnabled = Night.CanLengthen(a);
            on.IsChecked = a.On;
            allAuto.Visible(a.Manual.Count > 0);
        });
        return UI.VStack(8, eventRow, lengthRow, onRow);
    }
}
