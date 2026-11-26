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
    bool _knobsOpen = Defaults.Standard.Bool("nightCardKnobsOpen");
    Button? _header;
    string? _shape;
    readonly List<Action<ArcStatus>> _updates = [];
    readonly Stack _body = UI.VStack(10);
    Border? _card;

    // the header
    readonly FontIcon _moon = UI.Icon("moon.stars").Secondary();
    readonly TextBlock _title = UI.Text("", Font.Headline);
    readonly FontIcon _hand = UI.Icon("hand.raised.fill", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
    readonly FontIcon _fog = UI.Icon("cloud.fog.fill", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
    readonly FontIcon _sparkles = UI.Icon("sparkles", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
    readonly FontIcon _star = UI.Icon("star.circle.fill", Theme.Size(Font.Caption)).Foreground(Tint.Orange);
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
                UI.VStack(1, UI.HStack(5, _title, _sparkles, _star, _fog, _hand).Leading(), _clock.Leading()),
                UI.Spacer(8),
                _countdown,
                _chevron),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
        }.Borderless();
        _header = header;
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
        var shape = $"{_open}|{_knobsOpen}|{arc.On}|{arc.Hazers > 0}|{arc.Lightshow is not null}|{arc.Level is not null}|{arc.Levels}|{string.Join(",", (arc.NamedShows ?? []).Select(n => $"{n.Key}={n.Title}={n.Genre}"))}|{string.Join(",", arc.Stages.Select(s => string.Join("=", s)))}|{string.Join(",", arc.Events.Select(e => string.Join("=", e)))}";
        if (shape != _shape)
        {
            _shape = shape;
            BuildBody(arc);
            _card.Width = 340;
            _header?.Tooltip(_open ? L("Close the night's card: the stage and the intensity stay")
                : L("Open the night: the Lightshow, the knobs the show arc turns, the haze and the night's length"));
            _chevron.RenderTransform = new RotateTransform { Angle = _open ? 180 : 0 };
        }
        UpdateHeader(arc);
        foreach (var u in _updates) u(arc);
    }

    void UpdateHeader(ArcStatus arc)
    {
        _moon.Glyph = Symbols.Glyph(arc.On ? "moon.stars" : "moon.zzz");
        _title.Text = Night.Title(arc);
        _hand.Visible(arc.Manual.Count > 0).Tooltip(Night.HeldHelp(arc));
        _fog.Visible(arc.Haze is not null).Tooltip(L("You push the haze"));
        _sparkles.Visible(arc.Lightshow == true).Tooltip(L("Lightshow: every track played as a show piece"));
        _star.Visible(arc.NamedShow is not null).Tooltip(arc.NamedShow is { } named ? L("Named show: {0}", named.Title) : "");
        _clock.Text = Night.Clock(arc);
        var left = Night.Countdown(arc);
        _countdown.Visible(left is not null);
        _countdown.Text = left ?? "";
        _countdown.Foreground(Night.Over(arc) ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorPrimaryBrush"));
        _countdown.Tooltip(Night.Over(arc) ? L("Over the night's length") : L("Left of the night"));
    }

    void BuildBody(ArcStatus arc)
    {
        _body.Children.Clear();
        _updates.Clear();
        // what is reached for most, there without opening the card: the stage and the intensity
        if (arc.On) _body.Children.Add(StageRow(arc));
        if (arc.Level is not null) _body.Children.Add(LevelRow(arc));
        _body.Visible(_body.Children.Count > 0);
        if (!_open) return;
        _body.Children.Add(UI.Divider());
        if (arc.Lightshow is not null)
        {
            _body.Children.Add(LightshowRow(arc));
            if (arc.NamedShows is { Count: > 0 } shows) _body.Children.Add(NamedShowRow(shows));
            _body.Children.Add(UI.Divider());
        }
        if (arc.On)
        {
            _body.Children.Add(HeatRow());
            _body.Children.Add(KnobsHeader());
            if (_knobsOpen)
                foreach (var (title, knobs) in Knob.Sections)
                {
                    _body.Children.Add(UI.Text(title.ToUpperInvariant(), Font.Caption2).Bold().Secondary().Margin(0, 2, 0, 0).Leading());
                    foreach (var k in knobs) _body.Children.Add(KnobRow(k));
                }
            _body.Children.Add(UI.Divider());
        }
        if (arc.Hazers > 0)
        {
            _body.Children.Add(UI.Text(L("HAZE"), Font.Caption2).Bold().Secondary().Margin(0, 2, 0, 0).Leading());
            _body.Children.Add(HazeRow());
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
        var auto = UI.Button(L("Auto"), () => Send(ArcMessage.Auto(knob.Id))).Borderless().Font(Font.Caption);
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
            auto.Foreground(manual ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Accent));
            auto.Tooltip(manual ? L("Give this knob back to the show arc") : L("The show arc turns this knob"));
            row.Tooltip(Night.KnobHelp(knob, arc));
        });
        return row;
    }

    // MARK: the Lightshow: switched on by hand for a song that should be a light show of its own (a demo, the
    // night's anthem); every track is then played hit by hit, building up section by section to the climax

    UIElement LightshowRow(ArcStatus arc)
    {
        var on = arc.Lightshow == true;
        var icon = UI.Icon("sparkles").Frame(width: 18);
        var status = UI.Text("", Font.Caption);
        var toggle = UI.Toggle("", on, v => Send(ArcMessage.Lightshow(v)));
        _updates.Add(a =>
        {
            var now = a.Lightshow == true;
            toggle.SetOn(now);
            status.Text = Night.LightshowStatus(now);
            var tint = now ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush");
            status.Foreground(tint);
            icon.Foreground(tint);
        });
        var title = UI.Text(L("Lightshow"), Font.Callout).Bold();
        // the line wraps (it is longer while on), so the switch stays in the card
        return UI.HStack(8, icon, UI.VStack(1, title.Leading(), status.Wrap().Leading()).Grow(), toggle)
            .Tooltip(Night.LightshowHelp);
    }

    // MARK: the operator's intensity level: how hard the show plays, 1 … 5. 2 is the show as designed; 1 a step
    // gentler; 3, 4 and 5 ever harder, 5 with a lot of strobing and very fast waves through the rig

    UIElement LevelRow(ArcStatus arc)
    {
        var icon = UI.Icon("flame").Frame(width: 18);
        var status = UI.Text("", Font.Caption);
        var levels = Enumerable.Range(1, Math.Max(arc.Levels ?? 5, 1)).ToList();
        var picker = UI.Segmented(levels, arc.Level ?? 2, l => l.ToString(), l => Send(ArcMessage.Level(l)));
        _updates.Add(a =>
        {
            var level = a.Level ?? 2;
            foreach (var b in picker.Children.OfType<ToggleButton>()) b.IsChecked = b.Tag is int t && t == level;
            status.Text = Night.LevelStatus(level);
            var tint = level > 2 ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush");
            status.Foreground(tint);
            icon.Foreground(tint);
        });
        var title = UI.Text(L("Intensity"), Font.Callout).Bold().Frame(width: 62);
        // one line, there in the closed card too; what the level does is said in the open card
        var row = UI.HStack(8, icon, title, picker.Grow());
        status.Visible(_open);
        return UI.VStack(4, row, status.Wrap().Leading().Margin(26, 0, 0, 0)).Tooltip(Night.LevelHelp);
    }

    // MARK: the DJ's named show: a fixed style for their whole set (Prydz Tomorrow …), per genre; None: the house
    // style of each track's genre. The tracks are planned again in the background when it changes.

    UIElement NamedShowRow(IReadOnlyList<NamedShow> shows)
    {
        var icon = UI.Icon("star.circle").Frame(width: 18);
        var status = UI.Text("", Font.Caption);
        var label = UI.Text(L("None"), Font.Caption);
        var picker = UI.MenuButton(label, () =>
        {
            var named = Arc?.Named ?? "";
            var menu = UI.Menu(UI.Choice(L("None"), "named", named == "", () => Send(ArcMessage.Named(""))));
            foreach (var genre in Night.NamedShowGenres(shows))
            {
                menu.Items.Add(UI.Separator());
                menu.Items.Add(UI.Note(Formatting.Capitalized(genre)));
                foreach (var show in shows.Where(s => s.Genre == genre))
                    menu.Items.Add(UI.Choice(show.Title, "named", named == show.Key, () => Send(ArcMessage.Named(show.Key))));
            }
            return menu;
        }).Small();
        _updates.Add(a =>
        {
            label.Text = a.NamedShow?.Title ?? L("None");
            status.Text = Night.NamedShowStatus(a);
            var tint = Night.NamedShowPlaying(a) ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush");
            status.Foreground(tint);
            icon.Foreground(tint);
        });
        var title = UI.Text(L("Named Show"), Font.Callout).Bold();
        return UI.HStack(8, icon, UI.VStack(1, title.Leading(), status.Wrap().Leading()).Grow(), picker)
            .Tooltip(Night.NamedShowHelp);
    }

    // MARK: the haze push: the hazers at a level for a while (to fill the room), then the room kept that hazy
    // with bursts at that level until given back (Auto)

    UIElement HazeRow()
    {
        var level = Defaults.Standard.Contains("hazePushLevel") ? Defaults.Standard.Double("hazePushLevel") : 50;
        var seconds = Defaults.Standard.Contains("hazePushSeconds") ? Defaults.Standard.Integer("hazePushSeconds") : 30;
        var every = Defaults.Standard.Contains("hazePushEvery") ? Defaults.Standard.Integer("hazePushEvery") : 30;
        var pct = UI.Text($"{Num.Round(level)} %", Font.Caption).Secondary().Frame(width: 40);
        pct.TextAlignment = TextAlignment.Right;
        var slider = UI.Slider(level, 5, 100, v =>
        {
            level = v;
            pct.Text = $"{Num.Round(v)} %";
            Defaults.Standard.Set("hazePushLevel", v);
        }, step: 5);
        var output = UI.HStack(8,
            UI.Icon("cloud.fog").Secondary().Frame(width: 18),
            UI.Text(L("Output"), Font.Callout).Frame(width: 110),
            slider.Grow(),
            pct).Tooltip(L("How hard the hazers run while you push: a level at which yours make haze"));
        var stepper = Form.Stepper(seconds, 5, 600, n => $"{n} s", n =>
        {
            seconds = n;
            Defaults.Standard.Set("hazePushSeconds", n);
        }, step: 5);
        var time = UI.HStack(8,
            UI.Icon("timer").Secondary().Frame(width: 18),
            UI.Text(L("For"), Font.Callout).Frame(width: 110),
            stepper.Grow()).Tooltip(L("How long the push runs: long enough to fill the room"));
        var everyStepper = Form.Stepper(every, 10, 600, n => $"{n} s", n =>
        {
            every = n;
            Defaults.Standard.Set("hazePushEvery", n);
        }, step: 5);
        var push = UI.Button(L("Push"), () => Send(ArcMessage.Haze(level / 100, seconds, every))).Small()
            .Tooltip(L("Run the hazers at this output this long, then keep the room that hazy"));
        var again = UI.HStack(8,
            UI.Icon("repeat").Secondary().Frame(width: 18),
            UI.Text(L("Then every"), Font.Callout).Frame(width: 110),
            everyStepper.Grow(),
            push).Tooltip(L("How often a short burst at this output tops the haze up: shorter when the room loses it fast"));
        var status = UI.Text("", Font.Caption);
        var auto = UI.Button(L("Auto"), () => Send(ArcMessage.HazeAuto())).Borderless().Font(Font.Caption);
        _updates.Add(a =>
        {
            status.Text = Night.HazeStatus(a);
            status.Foreground(a.Haze is null ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Orange));
            push.Content = a.Haze is null ? L("Push") : L("Push Again");
            auto.IsEnabled = a.Haze is not null;
            auto.Tooltip(a.Haze is null ? L("The show hazes by itself") : L("Give the haze back to the show"));
        });
        return UI.VStack(6, output, time, again, UI.HStack(status, UI.Spacer(), auto));
    }

    // MARK: the stage the night is in, as a menu of the event's stages: pick one to go there now; Hold keeps the
    // night in it. What the menu shows is the stage the show plays in right now.

    UIElement StageRow(ArcStatus arc)
    {
        var stages = arc.Stages.Select(s => (Key: s.Count > 0 ? s[0] : "", Title: s.Count > 0 ? s[^1] : "")).ToList();
        var picker = UI.Picker(stages, stages.FirstOrDefault(s => s.Key == arc.Stage), s => s.Title, s => Send(ArcMessage.Stage(s.Key)))
            .Tooltip(L("The stage the night is in. Pick another to go there now (the arc carries on from there)"));
        picker.MinWidth = 0;
        var icon = UI.Icon("pin.fill").Frame(width: 18);
        var hold = new ToggleButton { Content = L("Hold") }.Small();
        hold.Click += (_, _) => Send(ArcMessage.Lock(hold.IsChecked == true));
        var held = UI.Text("", Font.Caption);
        held.Visible(_open);
        _updates.Add(a =>
        {
            picker.Select(stages.FirstOrDefault(s => s.Key == a.Stage));
            hold.IsChecked = a.Locked;
            hold.Tooltip(a.Locked ? L("Held: the arc stays in this stage. Click to let the music decide again")
                : L("Keep the night in this stage until you let go"));
            var tint = a.Locked ? Tint.Brush(Tint.Orange) : Theme.Brush("TextFillColorSecondaryBrush");
            icon.Foreground(tint);
            held.Text = a.Locked ? L("Held: the arc stays in this stage") : L("The music decides the stage");
            held.Foreground(tint);
        });
        var title = UI.Text(L("Stage"), Font.Callout).Bold().Frame(width: 62);
        return UI.VStack(4, UI.HStack(8, icon, title, picker.Grow(), hold), held.Leading().Margin(26, 0, 0, 0));
    }

    // MARK: the knobs the show arc turns, folded away until asked for: they are set once, not played

    UIElement KnobsHeader()
    {
        var held = UI.Text("", Font.Caption);
        var chevron = UI.Icon("chevron.down", Theme.Size(Font.Caption)).Secondary();
        chevron.RenderTransformOrigin = new Windows.Foundation.Point(0.5, 0.5);
        chevron.RenderTransform = new RotateTransform { Angle = _knobsOpen ? 180 : 0 };
        var b = new Button
        {
            Content = UI.HStack(8,
                UI.Icon("slider.horizontal.3").Secondary().Frame(width: 18),
                UI.Text(L("Knobs"), Font.Callout).Bold(),
                held,
                UI.Spacer(),
                chevron),
            HorizontalAlignment = HorizontalAlignment.Stretch,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
        }.Borderless().Tooltip(L("The knobs the show arc turns over the night: what is in play, the character, the reaction and the brightness. Take one over and it stays where you put it"));
        b.Padding = new Thickness(0);
        b.Click += (_, _) =>
        {
            _knobsOpen = !_knobsOpen;
            Defaults.Standard.Set("nightCardKnobsOpen", _knobsOpen);
            Refresh();
        };
        _updates.Add(a =>
        {
            held.Text = a.Manual.Count == 0 ? L("the show arc turns them") : L("you hold {0}", a.Manual.Count);
            held.Foreground(a.Manual.Count == 0 ? Theme.Brush("TextFillColorSecondaryBrush") : Tint.Brush(Tint.Orange));
        });
        return b;
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
            UI.Text(L("Music heat"), Font.Callout).Frame(width: 110),
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
        var eventRow = UI.HStack(8, UI.Text(L("Event"), Font.Callout), picker.Grow())
            .Tooltip(L("What kind of night: it names the stages, sets where in the night they may come, and the character (a wedding: fewer lasers, less smoke)"));

        var length = UI.Text("", Font.Body).Frame(width: 48);
        length.TextAlignment = TextAlignment.Center;
        var minus = UI.IconButton("minus", "", () => { if (Arc is { } a) Send(ArcMessage.Length(a.Length - Night.Step)); }).Borderless();
        var plus = UI.IconButton("plus", "", () => { if (Arc is { } a) Send(ArcMessage.Length(a.Length + Night.Step)); }).Borderless();
        var lengthRow = UI.HStack(8, UI.Text(L("Length"), Font.Callout), UI.Spacer(), minus, length, plus)
            .Tooltip(L("How long the night is: the countdown, and where the warm-up and the finale belong (a quarter of an hour per click)"));

        var on = UI.Check(L("Show arc"), arc.On, v => Send(ArcMessage.Enabled(v))).Tooltip(L("Off: the lights play every track as the director made it, at full"));
        var allAuto = UI.Button(L("All Auto"), () => Send(ArcMessage.Auto("all"))).Small();
        var newNight = UI.Button(L("New Night"), () => Send(ArcMessage.Reset())).Small()
            .Tooltip(L("Start again: the clock waits for the music, the night begins with the warm-up"));
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
