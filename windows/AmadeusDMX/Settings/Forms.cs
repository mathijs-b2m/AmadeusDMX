// SwiftUI's grouped Form, for the pages ported here (Settings, the Set page's inspector, DMX Output, the wizard):
// sections on cards with a header above and a footer below, rows of a label and its control (LabeledContent),
// and the alerts and confirmation dialogs the Mac shows (ContentDialog here). Built on Shared/UI.cs.
using Microsoft.UI.Xaml.Controls.Primitives;

namespace AmadeusDMX;

public static class Form
{
    /// A form: its sections one under the other, scrolling, at most `maxWidth` wide (SwiftUI's .formStyle(.grouped)).
    public static ScrollViewer Page(double maxWidth, params UIElement?[] sections) =>
        UI.Scroll(UI.VStack(18, sections).Padding(20).MaxWidth(maxWidth).Align(HorizontalAlignment.Stretch));

    /// A section: an optional header, its rows on a card (dividers between them), an optional footer.
    public static Stack Section(string? header, IEnumerable<UIElement?> rows, string? footer = null) =>
        Section(header is null ? null : UI.Text(header, Font.Subheadline).Secondary().Bold(), rows,
                footer is null ? null : Footer(footer));

    public static Stack Section(UIElement? header, IEnumerable<UIElement?> rows, UIElement? footer)
    {
        var card = UI.VStack(0);
        var first = true;
        foreach (var r in rows)
        {
            if (r is null) continue;
            if (!first) card.Children.Add(UI.Divider().Margin(0, 8, 0, 8));
            card.Children.Add(r);
            first = false;
        }
        return UI.VStack(6, header, first ? null : UI.Card(card, padding: 14), footer);
    }

    /// A section's footer: small secondary text.
    public static TextBlock Footer(string text) => UI.Text(text, Font.Caption).Secondary().Wrap().Margin(4, 0, 4, 0);

    /// A row: the label at the left, its control at the right (LabeledContent).
    public static Stack Row(string label, UIElement? control) => Row(UI.Text(label).Wrap(), control);

    public static Stack Row(UIElement label, UIElement? control)
    {
        var row = UI.HStack(12, label.Grow(), control);
        row.Alignment = 0.5;
        return row;
    }

    /// A row with a label and a secondary line under it.
    public static Stack Labeled(string title, string detail) =>
        UI.VStack(2, UI.Text(title), UI.Text(detail, Font.Caption).Secondary().Wrap());

    /// A label with a symbol in a colour (SwiftUI's Label + foregroundStyle), wrapping.
    public static Stack Note(string symbol, string text, Windows.UI.Color? color = null, Font font = Font.Callout)
    {
        var t = UI.Text(text, font).Wrap();
        var icon = UI.Icon(symbol, Theme.Size(font));
        var s = UI.HStack(6, icon, t.Grow());
        if (color is { } c) s.Foreground(c); else s.Secondary();
        return s;
    }

    /// A number with − and + (SwiftUI's Stepper): `format` says what it shows.
    public static Stack Stepper(int value, int min, int max, Func<int, string> format, Action<int> changed, int step = 1)
    {
        var current = value;
        var label = UI.Text(format(value));
        var row = UI.HStack(4);
        Button? minus = null, plus = null;
        void Apply()
        {
            label.Text = format(current);
            if (minus is not null) minus.IsEnabled = current - step >= min;
            if (plus is not null) plus.IsEnabled = current + step <= max;
        }
        minus = UI.IconButton("minus", "Less", () => { if (current - step >= min) { current -= step; Apply(); changed(current); } });
        plus = UI.IconButton("plus", "More", () => { if (current + step <= max) { current += step; Apply(); changed(current); } });
        row.Children.Add(label.Grow());
        row.Children.Add(minus);
        row.Children.Add(plus);
        Apply();
        return row;
    }

    /// A text field that reports on Enter (and when it loses focus) only: SwiftUI's .onSubmit.
    public static TextBox Submit(string placeholder, string text, Action<string> submitted)
    {
        var t = new TextBox { PlaceholderText = placeholder, Text = text, MinWidth = 120 };
        var last = text;
        void Done()
        {
            if (t.Text == last) return;
            last = t.Text;
            submitted(t.Text);
        }
        t.KeyDown += (_, e) => { if (e.Key == Windows.System.VirtualKey.Enter) { Done(); e.Handled = true; } };
        t.LostFocus += (_, _) => Done();
        return t;
    }

    /// Radio choices one under the other (SwiftUI's .radioGroup).
    public static Stack Radio<T>(IReadOnlyList<T> items, T selected, Func<T, string> title, Action<T> changed, bool horizontal = false)
    {
        var group = Guid.NewGuid().ToString();
        var s = horizontal ? UI.HStack(16) : UI.VStack(4);
        foreach (var i in items)
        {
            var r = new RadioButton { Content = title(i), GroupName = group, IsChecked = EqualityComparer<T>.Default.Equals(i, selected), MinWidth = 0 };
            r.Checked += (_, _) => changed(i);
            s.Children.Add(r);
        }
        return s;
    }

    /// A toggle button that stays down while on (SwiftUI's Toggle with .toggleStyle(.button)).
    public static ToggleButton ToggleButton(UIElement label, bool on, Action<bool> changed)
    {
        var b = new ToggleButton { Content = label, IsChecked = on };
        b.Click += (_, _) => changed(b.IsChecked == true);
        return b;
    }
}

/// The Mac's alerts and confirmation dialogs.
public static class Dialogs
{
    /// "Couldn’t …": a message and OK.
    public static async Task Alert(XamlRoot? root, string title, string message)
    {
        if (root is null) return;
        await Show(new ContentDialog
        {
            XamlRoot = root, Title = title, Content = UI.Text(message).Wrap().Selectable(), CloseButtonText = "OK",
            DefaultButton = ContentDialogButton.Close,
        });
    }

    /// A question with one action (destructive or not) and Cancel: true when the action was chosen.
    public static async Task<bool> Confirm(XamlRoot? root, string title, string message, string action, bool destructive = false)
    {
        if (root is null) return false;
        var d = new ContentDialog
        {
            XamlRoot = root, Title = title, Content = UI.Text(message).Wrap(), PrimaryButtonText = action, CloseButtonText = "Cancel",
            DefaultButton = destructive ? ContentDialogButton.Close : ContentDialogButton.Primary,
        };
        return await Show(d) == ContentDialogResult.Primary;
    }

    /// Asks for a text (Rename…): the text, or nil when cancelled.
    public static async Task<string?> AskText(XamlRoot? root, string title, string placeholder, string text, string action)
    {
        if (root is null) return null;
        var field = new TextBox { PlaceholderText = placeholder, Text = text, MinWidth = 280 };
        var d = new ContentDialog
        {
            XamlRoot = root, Title = title, Content = field, PrimaryButtonText = action, CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary,
        };
        field.Loaded += (_, _) => { field.Focus(FocusState.Programmatic); field.SelectAll(); };
        return await Show(d) == ContentDialogResult.Primary ? field.Text : null;
    }

    /// One ContentDialog at a time per window: WinUI refuses a second one while another is open.
    static readonly SemaphoreSlim One = new(1, 1);

    public static async Task<ContentDialogResult> Show(ContentDialog d)
    {
        await One.WaitAsync();
        try { return await d.ShowAsync(); }
        finally { One.Release(); }
    }

    /// Opens a folder in File Explorer, with a file selected (the Mac's "Show in Finder").
    public static void ShowInExplorer(string path)
    {
        try
        {
            var psi = File.Exists(path)
                ? new System.Diagnostics.ProcessStartInfo("explorer.exe") { ArgumentList = { $"/select,{path}" } }
                : new System.Diagnostics.ProcessStartInfo("explorer.exe") { ArgumentList = { path } };
            System.Diagnostics.Process.Start(psi);
        }
        catch (System.ComponentModel.Win32Exception) { }
    }

    /// Opens a web page in the default browser (SwiftUI's Link).
    public static void OpenURL(string url)
    {
        try { System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (System.ComponentModel.Win32Exception) { }
    }

    /// The window an element is in, for pickers (AppWindow id).
    public static Microsoft.UI.WindowId? WindowOf(UIElement e) => e.XamlRoot?.ContentIslandEnvironment?.AppWindowId;

    /// Choose a folder (NSOpenPanel with canChooseDirectories).
    public static async Task<string?> ChooseFolder(UIElement from, string commit = "Choose")
    {
        if (WindowOf(from) is not { } id) return null;
        var picker = new Microsoft.Windows.Storage.Pickers.FolderPicker(id) { CommitButtonText = commit };
        return (await picker.PickSingleFolderAsync())?.Path;
    }
}
