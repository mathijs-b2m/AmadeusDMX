// Views in code: small helpers that make WinUI read like the SwiftUI they are ported from.
//
//   UI.VStack(12,
//       UI.HStack(UI.Icon("waveform").Foreground(Tint.Green), UI.Text(model.ShowTitle, Font.Headline), UI.Spacer(),
//                 UI.Text("40 fps", Font.Caption).Secondary()),
//       UI.Button("Stop", model.StopShow).Prominent())
//     .Padding(12)
//     .Bind(model, nameof(AppModel.ShowTitle), v => …)
//
// Layout: VStack/HStack (Stack: SwiftUI's spacing, Spacer and alignment), ZStack (children on top of each other),
// Scroll, Card, Section. Text and symbols: Text(…, Font), Label(symbol, title), Icon(SF Symbol name: Symbols.cs).
// Controls: Button, IconButton, Toggle, Check, Slider, Field, Picker, Segmented, Progress, Menu/Item.
// Modifiers are extension methods returning the element (Padding, Frame, Font, Foreground, Tooltip, Disabled, …).
// State: `.Bind(model, nameof(Prop), el => …)` runs now and on every change while the element is on screen (also
// `.Bind(model, [nameof(A), nameof(B)], …)` and `.BindAll(model, …)`);
// `UI.Live(model, () => …)` rebuilds a part of the view when the model changes (SwiftUI's re-evaluated body).
//
// A view the feed updates 5 times a second must stay clickable: setting a brush or a tooltip again restarts the
// control's hover look and closes its tooltip, and a button rebuilt between press and release never gets its click.
// So Foreground, Background and Tooltip leave an unchanged value alone, and rebuilds go through `host.Rebuild(…)`,
// which waits while a pointer is pressed in the host.
using System.ComponentModel;
using System.Runtime.CompilerServices;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml.Controls.Primitives;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.System;
using Windows.UI;

namespace AmadeusDMX;

/// SwiftUI's text styles, on Windows's type ramp (Body is 14 px).
public enum Font { LargeTitle, Title, Title2, Title3, Headline, Body, Callout, Subheadline, Footnote, Caption, Caption2, Mono, MonoCaption }

public static partial class UI
{
    // MARK: layout

    public const double DefaultSpacing = 8;

    public static Stack VStack(params UIElement?[] children) => VStack(DefaultSpacing, children);

    public static Stack VStack(double spacing, params UIElement?[] children) => Fill(new Stack(Orientation.Vertical, spacing), children);

    public static Stack HStack(params UIElement?[] children) => HStack(DefaultSpacing, children);

    public static Stack HStack(double spacing, params UIElement?[] children) => Fill(new Stack(Orientation.Horizontal, spacing), children);

    /// Children on top of each other (the first at the back), each aligned by its own alignment.
    public static Grid ZStack(params UIElement?[] children) => Fill(new Grid(), children);

    static T Fill<T>(T panel, IEnumerable<UIElement?> children) where T : Panel
    {
        foreach (var c in children) if (c is not null) panel.Children.Add(c);
        return panel;
    }

    /// Takes the free room in a stack (at least `min`).
    public static FrameworkElement Spacer(double min = 0)
    {
        var b = new Border { IsHitTestVisible = false };
        b.SetValue(Stack.SpacerProperty, min);
        return b;
    }

    /// A thin line: across a VStack, or upright in an HStack (`vertical`).
    public static Border Divider(bool vertical = false) => new()
    {
        Background = Theme.Brush("DividerStrokeColorDefaultBrush"),
        Height = vertical ? double.NaN : 1,
        Width = vertical ? 1 : double.NaN,
        VerticalAlignment = vertical ? VerticalAlignment.Stretch : VerticalAlignment.Center,
    };

    public static ScrollViewer Scroll(UIElement content, bool horizontal = false) => new()
    {
        Content = content,
        HorizontalScrollBarVisibility = horizontal ? ScrollBarVisibility.Auto : ScrollBarVisibility.Disabled,
        HorizontalScrollMode = horizontal ? ScrollMode.Auto : ScrollMode.Disabled,
        VerticalScrollBarVisibility = horizontal ? ScrollBarVisibility.Disabled : ScrollBarVisibility.Auto,
    };

    /// A rounded panel on the layer colour (SwiftUI's `.background(.quaternary, in: .rect(cornerRadius:))`, glass).
    public static Border Card(UIElement content, double padding = 12, double corner = 10) => new()
    {
        Child = content,
        Padding = new Thickness(padding),
        CornerRadius = new CornerRadius(corner),
        Background = Theme.Brush("CardBackgroundFillColorDefaultBrush"),
        BorderBrush = Theme.Brush("CardStrokeColorDefaultBrush"),
        BorderThickness = new Thickness(1),
    };

    /// A titled group of rows (a Form's Section): the title small and secondary above them.
    public static Stack Section(string title, params UIElement?[] rows) =>
        VStack(6, [Text(title, Font.Subheadline).Secondary().Bold(), .. rows]);

    /// A row of a form: a label at the left, its control at the right.
    public static Stack Row(string label, UIElement control) => HStack(Text(label), Spacer(), control);

    /// Nothing to show yet (SwiftUI's ContentUnavailableView): a big symbol, a title, a line, actions.
    public static FrameworkElement Unavailable(string symbol, string title, string description, params UIElement[] actions)
    {
        var s = VStack(10, [
            Icon(symbol, 44).Secondary(),
            Text(title, Font.Title2).Center(),
            Text(description, Font.Body).Secondary().Center().Wrap().MaxWidth(420),
            actions.Length > 0 ? HStack(8, actions).Margin(0, 8, 0, 0) : null,
        ]);
        s.Alignment = 0.5;
        s.HorizontalAlignment = HorizontalAlignment.Center;
        s.VerticalAlignment = VerticalAlignment.Center;
        return s;
    }

    // MARK: text and symbols

    public static TextBlock Text(string text, Font font = Font.Body) =>
        new TextBlock { Text = text, TextTrimming = TextTrimming.CharacterEllipsis, VerticalAlignment = VerticalAlignment.Center }.Font(font);

    /// A symbol and a title (SwiftUI's Label).
    public static Stack Label(string symbol, string title, Font font = Font.Body)
    {
        var size = Theme.Size(font);
        return HStack(6, Icon(symbol, size).Font(font), Text(title, font));
    }

    /// An SF Symbol's Windows counterpart (Symbols.cs), or a Segoe Fluent Icons glyph itself.
    public static FontIcon Icon(string symbol, double size = 16) => new()
    {
        Glyph = Symbols.Glyph(symbol),
        FontFamily = Theme.SymbolFont,
        FontSize = size,
        VerticalAlignment = VerticalAlignment.Center,
    };

    // MARK: controls

    public static Button Button(string title, Action action) => Button(title, action, null);

    public static Button Button(string title, Action action, string? symbol)
    {
        var b = new Button { Content = symbol is null ? title : Label(symbol, title) };
        b.Click += (_, _) => action();
        return b;
    }

    /// A button with only a symbol (and its tooltip).
    public static Button IconButton(string symbol, string tooltip, Action action)
    {
        var b = new Button { Content = Icon(symbol, 14), Padding = new Thickness(8, 6, 8, 6) }.Tooltip(tooltip);
        b.Click += (_, _) => action();
        return b;
    }

    /// A button that looks like a link (SwiftUI's `.buttonStyle(.link)`).
    public static HyperlinkButton Link(string title, Action action)
    {
        var b = new HyperlinkButton { Content = title, Padding = new Thickness(0) };
        b.Click += (_, _) => action();
        return b;
    }

    /// A switch (SwiftUI's Toggle with the switch style). `changed` runs on the user's changes only.
    public static ToggleSwitch Toggle(string title, bool on, Action<bool> changed)
    {
        var t = new ToggleSwitch { Header = string.IsNullOrEmpty(title) ? null : title, IsOn = on, OnContent = "", OffContent = "", MinWidth = 0 };
        t.Toggled += (_, _) => { if (!IsQuiet(t)) changed(t.IsOn); };
        return t;
    }

    /// Sets a switch without telling its `changed` (for Bind).
    public static void SetOn(this ToggleSwitch t, bool on) => Quietly(t, () => t.IsOn = on);

    // a control being set from the model, not by the user: its `changed` stays silent (UI thread only)
    static readonly HashSet<object> Quiet = new(ReferenceEqualityComparer.Instance);

    static void Quietly(object control, Action set)
    {
        Quiet.Add(control);
        try { set(); }
        finally { Quiet.Remove(control); }
    }

    static bool IsQuiet(object control) => Quiet.Contains(control);

    public static CheckBox Check(string title, bool on, Action<bool> changed)
    {
        var c = new CheckBox { Content = title, IsChecked = on, MinWidth = 0 };
        c.Click += (_, _) => changed(c.IsChecked == true);  // Click: the user's, never a change made in code
        return c;
    }

    /// `step`: the value snaps to it (0: continuous). `changed` runs while it is dragged.
    public static Slider Slider(double value, double min, double max, Action<double> changed, double step = 0)
    {
        var s = new Slider { Minimum = min, Maximum = max, Value = value, StepFrequency = step > 0 ? step : (max - min) / 1000 };
        if (step > 0) s.SnapsTo = SliderSnapsTo.StepValues;
        s.ValueChanged += (_, e) => { if (!IsQuiet(s)) changed(e.NewValue); };
        return s;
    }

    /// Sets a slider without telling its `changed` (for Bind).
    public static void SetValueQuietly(this Slider s, double v) => Quietly(s, () => s.Value = v);

    public static TextBox Field(string placeholder, string text, Action<string> changed)
    {
        var t = new TextBox { PlaceholderText = placeholder, Text = text };
        t.TextChanged += (_, _) => changed(t.Text);
        return t;
    }

    /// A drop-down of `items` (SwiftUI's Picker, menu style).
    public static ComboBox Picker<T>(IReadOnlyList<T> items, T selected, Func<T, string> title, Action<T> changed)
    {
        var c = new ComboBox { MinWidth = 120 };
        foreach (var i in items) c.Items.Add(new ComboBoxItem { Content = title(i), Tag = i });
        c.SelectedIndex = IndexOf(items, selected);
        c.SelectionChanged += (_, _) =>
        {
            if (c.SelectedItem is ComboBoxItem { Tag: T v } && !IsQuiet(c)) changed(v);
        };
        return c;
    }

    static int IndexOf<T>(IReadOnlyList<T> items, T value)
    {
        for (var i = 0; i < items.Count; i++) if (EqualityComparer<T>.Default.Equals(items[i], value)) return i;
        return -1;
    }

    /// Selects in a Picker without telling its `changed` (for Bind).
    public static void Select<T>(this ComboBox c, T value) => Quietly(c, () =>
        c.SelectedIndex = c.Items.Cast<ComboBoxItem>().ToList().FindIndex(i => i.Tag is T t && EqualityComparer<T>.Default.Equals(t, value)));

    /// Side-by-side choices (SwiftUI's segmented Picker): toggle buttons of which one is on.
    public static Stack Segmented<T>(IReadOnlyList<T> items, T selected, Func<T, string> title, Action<T> changed)
    {
        var row = HStack(2);
        var buttons = new List<ToggleButton>();
        foreach (var item in items)
        {
            var b = new ToggleButton { Content = title(item), IsChecked = EqualityComparer<T>.Default.Equals(item, selected), Tag = item };
            b.Click += (_, _) =>
            {
                foreach (var o in buttons) o.IsChecked = ReferenceEquals(o, b);
                changed(item);
            };
            buttons.Add(b);
            row.Children.Add(b.Grow());
        }
        return row;
    }

    /// 0..1 (nil: indeterminate).
    public static ProgressBar Progress(double? value) => new()
    {
        Minimum = 0, Maximum = 1, Value = value ?? 0, IsIndeterminate = value is null, VerticalAlignment = VerticalAlignment.Center,
    };

    public static ProgressRing Spinner(double size = 16) => new() { IsActive = true, Width = size, Height = size };

    // MARK: menus

    public static MenuFlyout Menu(params MenuFlyoutItemBase?[] items)
    {
        var m = new MenuFlyout();
        foreach (var i in items) if (i is not null) m.Items.Add(i);
        return m;
    }

    public static MenuFlyoutItem Item(string title, Action action, string? symbol = null)
    {
        var i = new MenuFlyoutItem { Text = title };
        if (symbol is not null) i.Icon = new FontIcon { Glyph = Symbols.Glyph(symbol), FontFamily = Theme.SymbolFont };
        i.Click += (_, _) => action();
        return i;
    }

    /// One of a group of choices in a menu (SwiftUI's inline Picker in a Menu).
    public static RadioMenuFlyoutItem Choice(string title, string group, bool on, Action action, string? symbol = null)
    {
        var i = new RadioMenuFlyoutItem { Text = title, GroupName = group, IsChecked = on };
        if (symbol is not null) i.Icon = new FontIcon { Glyph = Symbols.Glyph(symbol), FontFamily = Theme.SymbolFont };
        i.Click += (_, _) => action();
        return i;
    }

    /// A line of text in a menu that does nothing (SwiftUI's Text in a Menu).
    public static MenuFlyoutItem Note(string text) => new() { Text = text, IsEnabled = false };

    public static MenuFlyoutSeparator Separator() => new();

    public static MenuFlyoutSubItem SubMenu(string title, params MenuFlyoutItemBase?[] items)
    {
        var s = new MenuFlyoutSubItem { Text = title };
        foreach (var i in items) if (i is not null) s.Items.Add(i);
        return s;
    }

    /// A button that opens a menu (SwiftUI's Menu in a toolbar).
    public static DropDownButton MenuButton(UIElement label, Func<MenuFlyout> menu)
    {
        var b = new DropDownButton { Content = label };
        var flyout = new MenuFlyout();
        b.Flyout = flyout;
        flyout.Opening += (_, _) =>  // built when opened: always the model as it is now
        {
            flyout.Items.Clear();
            foreach (var i in menu().Items.ToList()) flyout.Items.Add(i);
        };
        return b;
    }

    // MARK: state

    /// Runs `apply` now and whenever `property` of `model` changes while `element` is on screen; when it comes
    /// back on screen it catches up. On the UI thread, like everything a model changes.
    public static T Bind<T>(this T element, INotifyPropertyChanged model, string property, Action<T> apply) where T : FrameworkElement =>
        element.Bind(model, name => name is null || name == property, apply);

    /// Bind to every property of the model.
    public static T BindAll<T>(this T element, INotifyPropertyChanged model, Action<T> apply) where T : FrameworkElement =>
        element.Bind(model, _ => true, apply);

    /// Bind to several properties at once.
    public static T Bind<T>(this T element, INotifyPropertyChanged model, string[] properties, Action<T> apply) where T : FrameworkElement
    {
        var only = properties.ToHashSet();
        return element.Bind(model, name => name is null || only.Contains(name), apply);
    }

    static T Bind<T>(this T element, INotifyPropertyChanged model, Func<string?, bool> matches, Action<T> apply, bool applyNow = true)
        where T : FrameworkElement
    {
        if (applyNow) apply(element);
        var subscribed = false;
        void Changed(object? sender, PropertyChangedEventArgs e)
        {
            if (matches(e.PropertyName)) apply(element);
        }
        void Subscribe()
        {
            model.PropertyChanged += Changed;
            subscribed = true;
        }
        Subscribe();
        element.Loaded += (_, _) =>
        {
            if (subscribed) return;
            Subscribe();
            apply(element);  // what changed while it was away
        };
        element.Unloaded += (_, _) =>
        {
            if (element.IsLoaded || !subscribed) return;  // moved, not gone
            model.PropertyChanged -= Changed;
            subscribed = false;
        };
        return element;
    }

    /// A part of the view built again whenever the model changes (`properties`: only those; none: any).
    public static ContentControl Live(INotifyPropertyChanged model, Func<UIElement?> build, params string[] properties)
    {
        var host = new ContentControl
        {
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
            VerticalContentAlignment = VerticalAlignment.Stretch,
            IsTabStop = false,
        };
        void Rebuild(ContentControl c) => c.Rebuild(build);
        return properties.Length == 0 ? host.BindAll(model, Rebuild) : host.Bind(model, properties, Rebuild);
    }

    /// Like Live, following several models (the app's, the feed, the power meter…).
    public static ContentControl Live(INotifyPropertyChanged[] models, Func<UIElement?> build)
    {
        var host = new ContentControl
        {
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
            VerticalContentAlignment = VerticalAlignment.Stretch,
            IsTabStop = false,
        };
        host.Content = build();
        foreach (var m in models) host.Bind(m, name => true, c => c.Rebuild(build), applyNow: false);
        return host;
    }

    /// Fills `host` with what `build` makes, but not while a pointer is pressed in it: the button under the pointer
    /// would be thrown away between press and release, and its click lost. Then it waits for the release (the click
    /// has run by then) and builds once, with the model as it is then.
    public static void Rebuild(this ContentControl host, Func<UIElement?> build)
    {
        var presses = Presses.GetValue(host, Track);
        if (presses.Down) presses.Pending = build;
        else host.Content = build();
    }

    sealed class PressState
    {
        public bool Down;
        public Func<UIElement?>? Pending;
    }

    static readonly ConditionalWeakTable<ContentControl, PressState> Presses = new();

    static PressState Track(ContentControl host)
    {
        var state = new PressState();
        // handledEventsToo: buttons mark their pointer events handled
        host.AddHandler(UIElement.PointerPressedEvent, new PointerEventHandler((_, _) => state.Down = true), true);
        var up = new PointerEventHandler((_, _) =>
        {
            if (!state.Down) return;
            state.Down = false;
            if (state.Pending is not { } build) return;
            state.Pending = null;
            Later(() => host.Rebuild(build));  // after the click's own handlers
        });
        host.AddHandler(UIElement.PointerReleasedEvent, up, true);
        host.AddHandler(UIElement.PointerCaptureLostEvent, up, true);
        host.AddHandler(UIElement.PointerCanceledEvent, up, true);
        // released outside with nothing captured: don't wait forever (only the host's own exit, not a child's bubbling up)
        host.AddHandler(UIElement.PointerExitedEvent, new PointerEventHandler((s, e) => { if (ReferenceEquals(e.OriginalSource, host)) up(s, e); }), true);
        return state;
    }

    /// The UI thread's queue, for work that must wait for the next turn (DispatchQueue.main.async).
    public static void Later(Action action) =>
        Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread()?.TryEnqueue(() => action());
}

/// Modifiers, SwiftUI style: each returns the element so they chain.
public static class Modifiers
{
    public static T Padding<T>(this T e, double all) where T : FrameworkElement => e.Padding(new Thickness(all));

    public static T Padding<T>(this T e, double horizontal, double vertical) where T : FrameworkElement =>
        e.Padding(new Thickness(horizontal, vertical, horizontal, vertical));

    public static T Padding<T>(this T e, Thickness t) where T : FrameworkElement
    {
        switch (e)
        {
            case Control c: c.Padding = t; break;
            case Border b: b.Padding = t; break;
            case TextBlock tb: tb.Padding = t; break;
            case Stack s: s.Padding = t; break;
            case Grid g: g.Padding = t; break;
            case StackPanel sp: sp.Padding = t; break;
            default: e.Margin = t; break;
        }
        return e;
    }

    public static T Margin<T>(this T e, double all) where T : FrameworkElement { e.Margin = new Thickness(all); return e; }

    public static T Margin<T>(this T e, double left, double top, double right, double bottom) where T : FrameworkElement
    {
        e.Margin = new Thickness(left, top, right, bottom);
        return e;
    }

    /// Fixed size (NaN: free), like `.frame(width:height:)`.
    public static T Frame<T>(this T e, double width = double.NaN, double height = double.NaN) where T : FrameworkElement
    {
        e.Width = width;
        e.Height = height;
        return e;
    }

    public static T MinWidth<T>(this T e, double w) where T : FrameworkElement { e.MinWidth = w; return e; }
    public static T MaxWidth<T>(this T e, double w) where T : FrameworkElement { e.MaxWidth = w; return e; }
    public static T MinHeight<T>(this T e, double h) where T : FrameworkElement { e.MinHeight = h; return e; }
    public static T MaxHeight<T>(this T e, double h) where T : FrameworkElement { e.MaxHeight = h; return e; }

    public static T Align<T>(this T e, HorizontalAlignment h) where T : FrameworkElement { e.HorizontalAlignment = h; return e; }
    public static T Align<T>(this T e, VerticalAlignment v) where T : FrameworkElement { e.VerticalAlignment = v; return e; }

    /// Takes a share of the free room in its stack (`.frame(maxWidth: .infinity)` along the stack).
    public static T Grow<T>(this T e, bool grow = true) where T : UIElement { Stack.SetGrow(e, grow); return e; }

    /// Stretches across its stack (`.frame(maxHeight: .infinity)` in an HStack).
    public static T Fill<T>(this T e) where T : FrameworkElement
    {
        Stack.SetFill(e, true);
        e.HorizontalAlignment = HorizontalAlignment.Stretch;
        e.VerticalAlignment = VerticalAlignment.Stretch;
        return e;
    }

    public static T Font<T>(this T e, Font font) where T : FrameworkElement
    {
        var (size, weight, family) = Theme.Style(font);
        switch (e)
        {
            case TextBlock t: t.FontSize = size; t.FontWeight = weight; if (family is not null) t.FontFamily = family; break;
            case Control c: c.FontSize = size; c.FontWeight = weight; if (family is not null) c.FontFamily = family; break;
            case FontIcon i: i.FontSize = size; break;
        }
        return e;
    }

    public static T Bold<T>(this T e) where T : FrameworkElement
    {
        switch (e)
        {
            case TextBlock t: t.FontWeight = FontWeights.SemiBold; break;
            case Control c: c.FontWeight = FontWeights.SemiBold; break;
            case Stack s: foreach (var child in s.Children.OfType<FrameworkElement>()) child.Bold(); break;  // a Label
        }
        return e;
    }

    public static T Foreground<T>(this T e, Brush brush) where T : FrameworkElement
    {
        switch (e)
        {
            case TextBlock t: if (!Same(t.Foreground, brush)) t.Foreground = brush; break;
            case Control c: if (!Same(c.Foreground, brush)) c.Foreground = brush; break;
            case IconElement i: if (!Same(i.Foreground, brush)) i.Foreground = brush; break;
            case Stack s: foreach (var child in s.Children.OfType<FrameworkElement>()) child.Foreground(brush); break;
        }
        return e;
    }

    public static T Foreground<T>(this T e, Color color) where T : FrameworkElement => e.Foreground(new SolidColorBrush(color));

    /// The secondary text colour (SwiftUI's `.foregroundStyle(.secondary)`).
    public static T Secondary<T>(this T e) where T : FrameworkElement => e.Foreground(Theme.Brush("TextFillColorSecondaryBrush"));

    public static T Background<T>(this T e, Brush brush) where T : FrameworkElement
    {
        switch (e)
        {
            case Control c: if (!Same(c.Background, brush)) c.Background = brush; break;
            case Border b: if (!Same(b.Background, brush)) b.Background = brush; break;
            case Panel p: if (!Same(p.Background, brush)) p.Background = brush; break;
        }
        return e;
    }

    // the same colour again (a new brush each update): a button's Background set anew takes back its hover look
    static bool Same(Brush? a, Brush b) =>
        ReferenceEquals(a, b) || a is SolidColorBrush x && b is SolidColorBrush y && x.Color == y.Color && x.Opacity == y.Opacity;

    public static T Background<T>(this T e, Color color) where T : FrameworkElement => e.Background(new SolidColorBrush(color));

    public static T Corner<T>(this T e, double radius) where T : FrameworkElement
    {
        switch (e)
        {
            case Control c: c.CornerRadius = new CornerRadius(radius); break;
            case Border b: b.CornerRadius = new CornerRadius(radius); break;
            case Grid g: g.CornerRadius = new CornerRadius(radius); break;
        }
        return e;
    }

    public static T Opacity<T>(this T e, double o) where T : UIElement { e.Opacity = o; return e; }

    public static T Tooltip<T>(this T e, string? text) where T : DependencyObject
    {
        var tip = string.IsNullOrEmpty(text) ? null : text;
        if (!Equals(ToolTipService.GetToolTip(e), tip)) ToolTipService.SetToolTip(e, tip);  // set again, an open one closes
        return e;
    }

    public static T Disabled<T>(this T e, bool disabled = true) where T : Control { e.IsEnabled = !disabled; return e; }

    public static T Visible<T>(this T e, bool visible) where T : UIElement
    {
        e.Visibility = visible ? Visibility.Visible : Visibility.Collapsed;
        return e;
    }

    public static TextBlock Wrap(this TextBlock t, int maxLines = 0)
    {
        t.TextWrapping = TextWrapping.WrapWholeWords;
        t.MaxLines = maxLines;
        return t;
    }

    public static TextBlock Lines(this TextBlock t, int n) { t.MaxLines = n; t.TextWrapping = n == 1 ? TextWrapping.NoWrap : TextWrapping.WrapWholeWords; return t; }

    public static TextBlock Center(this TextBlock t) { t.TextAlignment = TextAlignment.Center; t.HorizontalAlignment = HorizontalAlignment.Center; return t; }

    public static TextBlock Selectable(this TextBlock t) { t.IsTextSelectionEnabled = true; return t; }

    /// The accent-coloured button (SwiftUI's `.borderedProminent`).
    public static T Prominent<T>(this T b) where T : ButtonBase
    {
        b.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        return b;
    }

    /// A keyboard shortcut: Ctrl (⌘ on the Mac) + key, with Shift / Alt (⌥) if asked.
    public static T Shortcut<T>(this T e, VirtualKey key, VirtualKeyModifiers modifiers = VirtualKeyModifiers.Control) where T : UIElement
    {
        e.KeyboardAccelerators.Add(new KeyboardAccelerator { Key = key, Modifiers = modifiers });
        return e;
    }

    public static T OnTap<T>(this T e, Action action) where T : UIElement
    {
        e.Tapped += (_, _) => action();
        return e;
    }

    public static T Flyout<T>(this T b, FlyoutBase flyout) where T : Button { b.Flyout = flyout; return b; }
}
