// LED Wall Output (Show menu, Ctrl+Shift+L; mac/Sources/AmadeusDMX/Show/LEDWallOutputPanel.swift): where the LED
// wall's picture goes on this computer. A monitor (the HDMI or DisplayPort into the LED processor), the wall's
// rectangle on it in pixels (what the processor reads), a brightness ceiling, how far the picture runs ahead of the
// lights, and a test card to line it all up. A window of its own, like the Mac's.
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml.Media;

namespace AmadeusDMX;

public sealed partial class LEDWallOutputWindow : Window
{
    static LEDWallOutputWindow? _open;

    /// The window (one), brought to the front.
    public static void Open(AppModel model)
    {
        if (_open is null)
        {
            _open = new LEDWallOutputWindow(model);
            _open.Closed += (_, _) => _open = null;
        }
        model.WallOutput.RefreshScreens();
        _open.Activate();
    }

    LEDWallOutputWindow(AppModel model)
    {
        Title = L("LED Wall Output");
        var icon = System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico");
        if (File.Exists(icon)) AppWindow.SetIcon(icon);
        SystemBackdrop = new MicaBackdrop();
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;  // Resize is in pixels
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(580 * scale), (int)(760 * scale)));
        if (AppWindow.Presenter is OverlappedPresenter p) p.IsMaximizable = false;
        Content = new LEDWallOutputPanel(model).Build();
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(IntPtr hwnd);
}

public sealed class LEDWallOutputPanel(AppModel model)
{
    readonly WallOutputController _out = model.WallOutput;
    WallOutputSettings S => _out.Settings;

    void Edit(Func<WallOutputSettings, WallOutputSettings> change) => _out.Settings = change(_out.Settings);

    public FrameworkElement Build()
    {
        var o = _out;

        // MARK: on, where to

        var status = UI.Text("", Font.Caption).Wrap()
            .Bind(o, [nameof(WallOutputController.Settings), nameof(WallOutputController.Problem), nameof(WallOutputController.PlayingOn),
                      nameof(WallOutputController.OutputPixels)], t =>
            {
                t.Text = Status();
                if (o.Problem is not null && o.Settings.On) t.Foreground(Tint.Orange); else t.Secondary();
            });
        var on = UI.Toggle("", S.On, v => Edit(s => s with { On = v }))
            .Bind(o, nameof(WallOutputController.Settings), t => t.SetOn(S.On));
        var play = Form.Row(UI.VStack(2, UI.Label("tv", L("Play the LED Wall")), status), on);

        WallOutputSettings.TargetKind[] targets = [WallOutputSettings.TargetKind.Display, WallOutputSettings.TargetKind.Window];
        var target = UI.Picker(targets, S.Target, t => t == WallOutputSettings.TargetKind.Window ? L("In a Window") : L("Full Screen on a Display"),
                               t => Edit(s => s with { Target = t }))
            .Bind(o, nameof(WallOutputController.Settings), c => c.Select(S.Target));

        var displays = UI.Live(o, DisplayPicker, nameof(WallOutputController.Screens), nameof(WallOutputController.Settings));
        var connect = Form.Footer(L("Connect the LED processor (HDMI or DisplayPort) like a second display. Set it to Extend these displays, not Duplicate, in Settings › System › Display."))
            .Bind(o, [nameof(WallOutputController.Screens), nameof(WallOutputController.Settings)],
                  t => t.Visible(S.Target == WallOutputSettings.TargetKind.Display && o.Screens.Count < 2));
        var displayRow = UI.VStack(6, Form.Row(L("Display"), displays), connect)
            .Bind(o, nameof(WallOutputController.Settings), r => r.Visible(S.Target == WallOutputSettings.TargetKind.Display));

        var hint = Form.Footer("");
        void Hint(FrameworkElement _)
        {
            hint.Text = ShowHint() ?? "";
            hint.Visible(hint.Text.Length > 0);
        }
        hint.Bind(o, nameof(WallOutputController.Settings), Hint).Bind(model.Feed, [nameof(LiveFeed.Hello), nameof(LiveFeed.State)], Hint);
        var first = Form.Section((UIElement?)null, [play, Form.Row(L("Output"), target), displayRow], hint);

        // MARK: the wall on the monitor

        var whole = UI.Toggle("", S.Rect is null, w => Edit(s => s with { Rect = w ? null : DefaultRect() }))
            .Bind(o, nameof(WallOutputController.Settings), t => t.SetOn(S.Rect is null));
        var start = UI.HStack(12,
            PixelField("X", () => S.Rect?.X ?? 0, v => EditRect(r => r with { X = Math.Max(0, v) })),
            PixelField("Y", () => S.Rect?.Y ?? 0, v => EditRect(r => r with { Y = Math.Max(0, v) })));
        var size = UI.HStack(12,
            PixelField("W", () => S.Rect?.W ?? 1, v => EditRect(r => r with { W = Math.Max(1, v) }), min: 1),
            PixelField("H", () => S.Rect?.H ?? 1, v => EditRect(r => r with { H = Math.Max(1, v) }), min: 1));
        var rectRows = UI.VStack(10, Form.Row(L("Start|position"), start), Form.Row(L("Size"), size), PanelsRow())
            .Bind(o, nameof(WallOutputController.Settings), r => r.Visible(S.Rect is not null));
        var wall = Form.Section(L("The Wall on the Display"),
            [Form.Row(L("Whole Display"), whole), rectRows],
            L("In pixels from the display's top left, as the LED processor maps it (its input's start position and the wall's size). Black around it."))
            .Bind(o, nameof(WallOutputController.Settings), w => w.Visible(S.Target == WallOutputSettings.TargetKind.Display));

        // MARK: brightness, lead, test card

        var percent = UI.Text("", Font.Body).Secondary();
        percent.MinWidth = 48;
        percent.TextAlignment = TextAlignment.Right;
        var brightness = UI.Slider(S.Brightness, 0.05, 1, v => Edit(s => s with { Brightness = v }));
        brightness.Width = 220;
        var brightnessRow = Form.Row(L("Brightness"), UI.HStack(8, brightness, percent))
            .Bind(o, nameof(WallOutputController.Settings), _ =>
            {
                brightness.SetValueQuietly(S.Brightness);
                percent.Text = $"{(int)Math.Round(S.Brightness * 100, MidpointRounding.AwayFromZero)} %";
            });
        var ms = UI.Text("", Font.Body).Secondary();
        ms.MinWidth = 60;
        ms.TextAlignment = TextAlignment.Right;
        var lead = UI.Slider(S.LeadMs, WallOutputSettings.LeadRange.Lower, WallOutputSettings.LeadRange.Upper,
                             v => Edit(s => s with { LeadMs = Math.Round(v / 5, MidpointRounding.AwayFromZero) * 5 }), step: 5);
        lead.Width = 220;
        var leadRow = Form.Row(L("Ahead of the Lights"), UI.HStack(8, lead, ms))
            .Bind(o, nameof(WallOutputController.Settings), _ =>
            {
                lead.SetValueQuietly(S.LeadMs);
                ms.Text = $"{(int)S.LeadMs} ms";
            });
        var card = UI.Toggle("", S.TestPattern, v => Edit(s => s with { TestPattern = v }))
            .Bind(o, nameof(WallOutputController.Settings), t => t.SetOn(S.TestPattern));
        var panel = Form.Row(L("Panel Size"), PixelField("px", () => S.PanelPx,
                v => Edit(s => s with { PanelPx = Math.Min(WallOutputSettings.PanelRange.Upper, Math.Max(WallOutputSettings.PanelRange.Lower, v)) }),
                min: WallOutputSettings.PanelRange.Lower, max: WallOutputSettings.PanelRange.Upper))
            .Bind(o, nameof(WallOutputController.Settings), r => r.Visible(S.TestPattern));
        var look = Form.Section((string?)null, [brightnessRow, leadRow, Form.Row(L("Test Card"), card), panel],
            L("A wall is bright: a dark club wants far less than daylight. An LED processor holds the picture a frame or two (16–50 ms): run it that far ahead so the wall and the lights land on the same beat. The test card shows the wall's edges, the panels, colour bars and a moving bar that stutters when frames are dropped."));

        return Form.Page(560, first, wall, look);
    }

    string Status()
    {
        var o = _out;
        if (o.Problem is { } p && o.Settings.On) return p;
        if (o.PlayingOn is { } on)
        {
            var px = o.OutputPixels is { } x && o.Settings.Target != WallOutputSettings.TargetKind.Display ? $" · {x.W} × {x.H}" : "";
            return L("Playing on {0}", on + px);
        }
        return o.Settings.On ? L("Starting…") : L("Off");
    }

    /// What the show gives the wall, when it gives it nothing.
    string? ShowHint()
    {
        if (!S.On) return null;
        if (model.Feed.Hello is not { } h || model.Feed.State != FeedState.Connected) return L("The wall stays black until a show plays.");
        return h.Screen ? null : L("This show's rig has no LED wall: turn it on in the rig (Rigs) and the director plays it. Until then the wall stays black.");
    }

    UIElement DisplayPicker()
    {
        var o = _out;
        var items = new List<(string? Id, string Title)>();
        if (S.Display is null) items.Add((null, L("Choose…")));
        if (S.Display is { } id && o.ChosenScreen is null) items.Add((id, L("{0} (not connected)", S.DisplayName ?? L("A display"))));
        foreach (var s in o.Screens) items.Add((s.Id, s.HoldsApp ? L("{0} (Amadeus DMX is here)", s.Label) : s.Label));
        var picker = UI.Picker(items, items.FirstOrDefault(i => i.Id == S.Display), i => i.Title, i =>
        {
            if (i.Id is null) return;
            var name = o.Screens.FirstOrDefault(s => s.Id == i.Id)?.Name ?? S.DisplayName;
            Edit(s => s with { Display = i.Id, DisplayName = name });
        });
        picker.MinWidth = 260;
        return picker;
    }

    void EditRect(Func<PixelRect, PixelRect> change)
    {
        if (S.Rect is { } r) Edit(s => s with { Rect = change(r) });
    }

    /// A wall where the processor usually starts reading (the top left), the monitor's size to begin with.
    PixelRect DefaultRect()
    {
        var px = _out.ChosenScreen?.Pixels ?? (1920, 1080);
        return new PixelRect(0, 0, px.W, px.H);
    }

    /// A whole number of pixels (a TextField with a Stepper on the Mac).
    FrameworkElement PixelField(string label, Func<int> get, Action<int> set, int min = 0, int max = 100_000)
    {
        var following = false;   // the value set from the model isn't the user's
        var box = new NumberBox
        {
            Value = get(), Minimum = min, Maximum = max, SmallChange = 1, LargeChange = 10,
            SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline, Width = 120,
            NumberFormatter = new Windows.Globalization.NumberFormatting.DecimalFormatter { FractionDigits = 0, IsGrouped = false },
        };
        box.ValueChanged += (b, e) =>
        {
            if (following) return;
            if (double.IsNaN(e.NewValue)) { b.Value = get(); return; }   // an emptied field: what it was
            var v = (int)Math.Round(e.NewValue, MidpointRounding.AwayFromZero);
            if (v != get()) set(v);
        };
        var row = UI.HStack(4, UI.Text(label).Secondary(), box);
        row.Alignment = 0.5;
        return row.Bind(_out, nameof(WallOutputController.Settings), _ =>
        {
            following = true;
            try { if ((int)box.Value != get()) box.Value = get(); }
            finally { following = false; }
        });
    }

    /// The wall's size from its panels: columns × rows of the panel size.
    FrameworkElement PanelsRow()
    {
        int cols = 6, rows = 3;
        var of = UI.Text("", Font.Body).Secondary()
            .Bind(_out, nameof(WallOutputController.Settings), t => t.Text = L("of {0} px", S.PanelPx));
        var row = UI.HStack(8,
            Form.Stepper(cols, 1, 64, n => L("{0} across", n), n => cols = n),
            Form.Stepper(rows, 1, 64, n => L("{0} high", n), n => rows = n),
            of,
            UI.Button(L("Set|verb"), () =>
            {
                var p = WallOutputLayout.Panels(cols, rows, S.PanelPx);
                EditRect(r => r with { W = p.W, H = p.H });
            }));
        row.Alignment = 0.5;
        return Form.Row(L("From Panels"), row).Tooltip(L("The wall's size from its panels (the panel size is under Test Card)"));
    }
}
