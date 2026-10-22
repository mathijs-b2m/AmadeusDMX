// The editor's form controls. SwiftUI keeps a control while the values it shows change; a WinUI view rebuilt on
// every change would lose the slider being dragged. So the editor's panels are built once per *shape* (what is
// selected, which kind of truss…: `Keyed`) and each control follows its value on its own (quietly: setting it
// from the model doesn't count as the user's change).
using System.ComponentModel;
using System.Globalization;
using Microsoft.UI.Xaml.Controls.Primitives;

namespace AmadeusDMX;

public static class EditorUI
{
    /// A part rebuilt only when `key()` changes; the model's every change asks.
    public static ContentControl Keyed(INotifyPropertyChanged model, Func<string> key, Func<UIElement?> build) =>
        Keyed([model], key, build);

    /// Keyed, following several models (the editor's and the app's).
    public static ContentControl Keyed(INotifyPropertyChanged[] models, Func<string> key, Func<UIElement?> build)
    {
        var host = new ContentControl
        {
            HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
        };
        string? last = null;
        void Update(ContentControl c)
        {
            var k = key();
            if (k == last) return;
            last = k;
            c.Content = build();
        }
        foreach (var m in models) host.BindAll(m, Update);
        return host;
    }

    static readonly string[] Follow = [nameof(RigEditorModel.Version), nameof(RigEditorModel.Doc)];

    /// A labelled slider with its value; snaps to `step` (Swift: ValueSlider). `unit` " m" or "°".
    public static FrameworkElement ValueSlider(RigEditorModel editor, string title, Func<double> get, Action<double> set,
                                               Func<double> min, Func<double> max, double step = 0.1, string unit = " m")
    {
        double Clamp(double v) => Math.Min(Math.Max(v, min()), Math.Max(min(), max()));
        string Text(double v) => unit == "°" ? $"{(int)Math.Round(v, MidpointRounding.AwayFromZero)}°"
            : v.ToString("0.00", CultureInfo.InvariantCulture) + unit;
        var value = UI.Text(Text(get())).Secondary();
        value.TextAlignment = TextAlignment.Right;
        value.Width = 62;
        var following = false;  // the range and value set from the model: a value the slider coerces isn't the user's
        var slider = UI.Slider(Clamp(get()), min(), Math.Max(min(), max()), v =>
        {
            if (following) return;
            var snapped = Math.Round(v / step, MidpointRounding.AwayFromZero) * step;
            if (Math.Abs(snapped - get()) > 1e-9) set(snapped);
        }, step).MinWidth(120);
        var row = UI.HStack(8, UI.Text(title), UI.Spacer(), slider.Grow(), value);
        return row.Bind(editor, Follow, _ =>
        {
            following = true;
            try
            {
                slider.Minimum = Math.Min(min(), slider.Maximum);
                slider.Maximum = Math.Max(min(), max());
                slider.Minimum = min();
                slider.SetValueQuietly(Clamp(get()));
            }
            finally { following = false; }
            value.Text = Text(get());
        });
    }

    public static FrameworkElement ValueSlider(RigEditorModel editor, string title, Func<double> get, Action<double> set,
                                               double min, double max, double step = 0.1, string unit = " m") =>
        ValueSlider(editor, title, get, set, () => min, () => max, step, unit);

    /// A labelled number field with − and + (a Form's TextField with a number format and a Stepper), `min`…`max`,
    /// stepping by `step`; `unit` after it ("m").
    public static FrameworkElement NumberField(RigEditorModel editor, string title, Func<double> get, Action<double> set,
                                               double min, double max, double step = 0.1, string unit = "m", string? help = null)
    {
        var following = false;  // the value set from the model isn't the user's
        var box = new NumberBox
        {
            Value = get(), Minimum = min, Maximum = max, SmallChange = step, LargeChange = step * 5,
            SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline, Width = 130,
        };
        box.ValueChanged += (b, e) =>
        {
            if (following) return;
            if (double.IsNaN(e.NewValue)) { b.Value = get(); return; }   // an emptied field: what it was
            var v = Math.Min(max, Math.Max(min, Math.Round(e.NewValue, 2, MidpointRounding.AwayFromZero)));
            if (Math.Abs(v - get()) > 1e-9) set(v);
        };
        var row = UI.HStack(8, UI.Text(title), UI.Spacer(), box, UI.Text(unit).Secondary()).Tooltip(help);
        return row.Bind(editor, Follow, _ =>
        {
            following = true;
            try { if (Math.Abs(box.Value - get()) > 1e-9) box.Value = get(); }
            finally { following = false; }
        });
    }

    /// A switch with its title at the left (a Form's Toggle).
    public static FrameworkElement Toggle(RigEditorModel editor, string title, Func<bool> get, Action<bool> set, string? help = null)
    {
        var t = UI.Toggle("", get(), set);
        return UI.HStack(8, UI.Text(title).Wrap(2), UI.Spacer(), t).Tooltip(help)
            .Bind(editor, Follow, _ => t.SetOn(get()));
    }

    /// Side-by-side choices following the model (SwiftUI's segmented Picker on a Binding). `get` "" or an unknown
    /// value: none of them on (a mixed selection).
    public static FrameworkElement Segmented<T>(RigEditorModel editor, IReadOnlyList<T> items, Func<T> get, Func<T, string> title, Action<T> set)
    {
        var s = UI.Segmented(items, get(), title, set);
        return s.Bind(editor, Follow, row =>
        {
            var now = get();
            foreach (var b in row.Children.OfType<ToggleButton>()) b.IsChecked = b.Tag is T t && EqualityComparer<T>.Default.Equals(t, now);
        });
    }

    /// A drop-down following the model (SwiftUI's Picker on a Binding).
    public static FrameworkElement Picker<T>(RigEditorModel editor, string title, IReadOnlyList<T> items, Func<T> get, Func<T, string> name,
                                             Action<T> set)
    {
        var c = UI.Picker(items, get(), name, set);
        c.Bind(editor, Follow, x => x.Select(get()));
        return title.Length == 0 ? c : UI.Row(title, c);
    }

    /// A value with − and + (SwiftUI's Stepper). `text` is built again on every change.
    public static FrameworkElement Stepper(INotifyPropertyChanged model, Func<string> text, Action minus, Action plus, string? help = null)
    {
        var label = UI.Text(text());
        var row = UI.HStack(4, label, UI.IconButton("minus", "Less", minus), UI.IconButton("plus", "More", plus)).Tooltip(help);
        return row.BindAll(model, _ => label.Text = text());
    }

    /// A text field that follows the model unless it's being typed in.
    public static TextBox Field(RigEditorModel editor, string placeholder, Func<string> get, Action<string> set)
    {
        var t = new TextBox { PlaceholderText = placeholder, Text = get() };
        t.TextChanged += (_, _) => { if (t.FocusState != FocusState.Unfocused && t.Text != get()) set(t.Text); };
        return t.Bind(editor, Follow, x => { if (x.FocusState == FocusState.Unfocused && x.Text != get()) x.Text = get(); });
    }

    /// A title over the rows of a form (a Form's Section), with an optional footer.
    public static FrameworkElement Section(string? title, IEnumerable<UIElement?> rows, string? footer = null)
    {
        var body = UI.VStack(10, [.. rows]);
        return UI.VStack(6,
            title is null ? null : UI.Text(title, Font.Subheadline).Secondary().Bold(),
            UI.Card(body, 12, 8),
            footer is null ? null : UI.Text(footer, Font.Caption).Secondary().Wrap());
    }

    public static FrameworkElement Section(string? title, params UIElement?[] rows) => Section(title, rows, null);

    /// A row with its value at the right (SwiftUI's LabeledContent).
    public static FrameworkElement Labeled(string title, string value) => UI.HStack(8, UI.Text(title), UI.Spacer(), UI.Text(value).Secondary());

    /// SF Symbols the shared table doesn't have yet: their Segoe Fluent Icons glyphs (else the shared name).
    public static string Symbol(string name) => name switch
    {
        "airplane" => "",
        "circle" => "",
        "rays" => "",
        "bolt" => "",
        "headphones" => "",
        "exclamationmark.triangle.fill" => Symbols.Glyph(name),
        _ => name,
    };

    /// The fixture kinds' symbols (Swift: FixtureIcon, Sets/SetView.swift).
    public static string FixtureSymbol(string? kind) => kind switch
    {
        "moving_head" => "light.overhead.right",
        "moving_bar" or "par_bar" => "light.strip.2",
        "laser" => Symbol("rays"),
        "strobe" => Symbol("bolt"),
        "blinder" => "light.panel",
        "smoke" => "cloud.fog",
        _ => "light.recessed",
    };

    /// A message box (SwiftUI's .alert with one OK).
    public static async Task Alert(XamlRoot? root, string title, string message)
    {
        if (root is null) return;
        await new ContentDialog { XamlRoot = root, Title = title, Content = UI.Text(message).Wrap(), CloseButtonText = "OK" }.ShowAsync();
    }

    /// A question with one action (SwiftUI's confirmationDialog): true if it was chosen.
    public static async Task<bool> Confirm(XamlRoot? root, string title, string message, string action)
    {
        if (root is null) return false;
        var d = new ContentDialog
        {
            XamlRoot = root, Title = title, Content = UI.Text(message).Wrap(), PrimaryButtonText = action, CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Close,
        };
        return await d.ShowAsync() == ContentDialogResult.Primary;
    }
}
