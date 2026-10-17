// The engine's own output: what it prints (analysis, AI progress, VirtualDJ health), for when something
// needs explaining.
using System.Collections.ObjectModel;
using System.Globalization;
using Microsoft.UI.Xaml.Controls.Primitives;
using Windows.ApplicationModel.DataTransfer;

namespace AmadeusDMX;

public sealed class EngineView(AppModel model)
{
    int _which;
    string _filter = "";
    bool _follow = true;
    EngineProcess? _watching;
    readonly List<int> _shown = [];
    ObservableCollection<EngineProcess.LogLine> _lines = [];
    readonly ItemsRepeater _list = new() { ItemTemplate = new LogLineFactory() };
    readonly ScrollViewer _scroll = new();
    FrameworkElement? _empty;

    EngineProcess Proc => _which == 0 ? model.Engine : model.Setup;

    public FrameworkElement Build()
    {
        _list.ItemsSource = _lines;
        _scroll.Content = _list;
        _scroll.Padding = new Thickness(16, 4, 16, 8);
        _scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto;
        _scroll.HorizontalScrollMode = ScrollMode.Auto;

        var which = UI.Segmented([0, 1], _which, i => i == 0 ? "Show Engine" : "Setup Service", i => { _which = i; Watch(); });
        var filter = new AutoSuggestBox { PlaceholderText = "Filter", QueryIcon = new SymbolIcon(Symbol.Find), Width = 220 };
        filter.TextChanged += (_, _) => { _filter = filter.Text; Sync(); };
        // Ctrl+F: to the filter (the Mac's search field in the toolbar, ⌘F)
        var find = new Microsoft.UI.Xaml.Input.KeyboardAccelerator { Key = Windows.System.VirtualKey.F, Modifiers = Windows.System.VirtualKeyModifiers.Control };
        find.Invoked += (_, e) => { filter.Focus(FocusState.Keyboard); e.Handled = true; };
        var follow = new ToggleButton { Content = UI.Label("arrow.down.to.line", "Follow"), IsChecked = _follow }.Tooltip("Keep scrolling to the newest line");
        follow.Click += (_, _) => { _follow = follow.IsChecked == true; if (_follow) ScrollToEnd(); };
        var copy = UI.Button("Copy", Copy, "doc.on.doc");
        var clear = UI.Button("Clear", () => Proc.ClearLog(), "trash");
        var bar = UI.HStack(8, which, UI.Spacer(), filter, follow, copy, clear).Padding(16, 8);

        _empty = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center, IsTabStop = false };
        var content = UI.ZStack(_scroll, _empty);
        var page = UI.VStack(0, bar, content.Grow().Fill());
        page.KeyboardAccelerators.Add(find);
        page.Loaded += (_, _) => Watch();
        page.Unloaded += (_, _) => Unwatch();
        return page;
    }

    /// Follows the chosen process's log while the page is on screen.
    void Watch()
    {
        Unwatch();
        _watching = Proc;
        _watching.LogChanged += Sync;
        _shown.Clear();
        Sync();
    }

    void Unwatch()
    {
        if (_watching is not null) _watching.LogChanged -= Sync;
        _watching = null;
    }

    void Sync()
    {
        var proc = Proc;
        var empty = proc.Log.Count == 0;
        if (_empty is ContentControl e)
        {
            e.Content = empty ? UI.Unavailable("terminal", EngineLog.Empty(_which == 0), EngineLog.EmptyDetail(_which == 0)) : null;
            e.Visible(empty);
        }
        _scroll.Visible(!empty);
        var change = EngineLog.Sync(_shown, proc.Log, _filter);
        if (change.Reset)
        {
            _shown.Clear();
            _lines = new ObservableCollection<EngineProcess.LogLine>(change.Append);  // at once, not line by line
            _list.ItemsSource = _lines;
        }
        else
        {
            for (var i = 0; i < change.DropFront; i++) _lines.RemoveAt(0);
            _shown.RemoveRange(0, change.DropFront);
            foreach (var l in change.Append) _lines.Add(l);
        }
        _shown.AddRange(change.Append.Select(l => l.Id));
        if (_follow && (change.Reset || change.Append.Count > 0)) ScrollToEnd();
    }

    void ScrollToEnd() => UI.Later(() =>
    {
        _scroll.UpdateLayout();
        _scroll.ChangeView(null, _scroll.ScrollableHeight, null, true);
    });

    void Copy()
    {
        var text = new DataPackage();
        text.SetText(string.Join("\n", _lines.Select(l => l.Text)));
        Clipboard.SetContent(text);
    }
}

/// The log's rows, made and reused as they scroll into view (the list can hold 4000 lines).
sealed partial class LogLineFactory : IElementFactory
{
    readonly Stack<Stack> _spare = new();

    public UIElement GetElement(ElementFactoryGetArgs args)
    {
        var row = _spare.Count > 0 ? _spare.Pop() : Make();
        if (args.Data is EngineProcess.LogLine line)
        {
            var time = (TextBlock)row.Children[0];
            var text = (TextBlock)row.Children[1];
            time.Text = line.Date.ToString("T", CultureInfo.CurrentCulture);
            text.Text = line.Text;
            text.Foreground = ShowUI.Brush(EngineLog.Tone(line));
        }
        return row;
    }

    public void RecycleElement(ElementFactoryRecycleArgs args)
    {
        if (args.Element is Stack s) _spare.Push(s);
    }

    static Stack Make()
    {
        var time = UI.Text("", Font.Mono).Foreground(ShowUI.Tertiary);
        time.VerticalAlignment = VerticalAlignment.Top;
        var text = UI.Text("", Font.Mono).Selectable();
        text.TextTrimming = TextTrimming.None;
        text.VerticalAlignment = VerticalAlignment.Top;
        return UI.HStack(10, time, text).Padding(new Thickness(0, 2, 0, 2));
    }
}
