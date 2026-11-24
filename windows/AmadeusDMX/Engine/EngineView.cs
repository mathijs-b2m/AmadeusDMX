// The engine's own output: what it prints (analysis, AI progress, VirtualDJ health), for when something
// needs explaining. And the DMX trace: every value that goes out to the lights, as it changes.
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
    DMXTrace? _trace;
    ToggleButton? _tracing;
    Button? _reveal;
    AutoSuggestBox? _filterBox;
    readonly DispatcherTimer _timer = new();

    EngineProcess Proc => _which == 0 ? model.Engine : model.Setup;
    bool Tracing => _which == 2;

    /// The trace of the data folder in use (another workspace: another trace).
    DMXTrace? Trace()
    {
        var data = model.Workspace?.Data;
        if (data is null) { if (_trace is not null) _trace.Changed -= Sync; return _trace = null; }
        if (_trace?.Data == data) return _trace;
        if (_trace is not null) _trace.Changed -= Sync;
        _trace = new DMXTrace(data);
        if (_watchingTrace) _trace.Changed += Sync;
        return _trace;
    }

    bool _watchingTrace;

    public FrameworkElement Build()
    {
        _list.ItemsSource = _lines;
        _scroll.Content = _list;
        _scroll.Padding = new Thickness(16, 4, 16, 8);
        _scroll.HorizontalScrollBarVisibility = ScrollBarVisibility.Auto;
        _scroll.HorizontalScrollMode = ScrollMode.Auto;

        var which = UI.Segmented([0, 1, 2], _which, i => i == 0 ? L("Show Engine") : i == 1 ? L("Setup Service") : L("DMX Trace"), Choose);
        _whichRow = which;
        var filter = _filterBox = new AutoSuggestBox { PlaceholderText = L("Filter"), QueryIcon = new SymbolIcon(Symbol.Find), Width = 220 };
        filter.TextChanged += (_, _) => { _filter = filter.Text; Sync(); };
        // Ctrl+F: to the filter (the Mac's search field in the toolbar, ⌘F)
        var find = new Microsoft.UI.Xaml.Input.KeyboardAccelerator { Key = Windows.System.VirtualKey.F, Modifiers = Windows.System.VirtualKeyModifiers.Control };
        find.Invoked += (_, e) => { filter.Focus(FocusState.Keyboard); e.Handled = true; };
        var follow = new ToggleButton { Content = UI.Label("arrow.down.to.line", L("Follow")), IsChecked = _follow }.Tooltip(L("Keep scrolling to the newest line"));
        follow.Click += (_, _) => { _follow = follow.IsChecked == true; if (_follow) ScrollToEnd(); };
        var tracing = _tracing = new ToggleButton { Content = UI.Label("waveform.path", L("Trace DMX")), IsChecked = Trace()?.IsOn == true }
            .Tooltip(L("Write down every value that goes out to the lights, as it changes: when, which fixture, which channel"));
        tracing.Click += (_, _) =>
        {
            var on = tracing.IsChecked == true;
            Trace()?.Set(on);
            if (on && !Tracing) Choose(2);
        };
        var copy = UI.Button(L("Copy"), Copy, "doc.on.doc");
        _reveal = UI.Button(L("Show in File Explorer"), () => { if (Trace() is { } t) Dialogs.ShowInExplorer(File.Exists(t.Log) ? t.Log : Path.GetDirectoryName(t.Log)!); }, "folder")
            .Tooltip(L("The whole trace as a file (dmx-trace.log)"));
        var clear = UI.Button(L("Clear"), () => { if (Tracing) Trace()?.Clear(); else Proc.ClearLog(); }, "trash");
        var bar = UI.HStack(8, which, UI.Spacer(), filter, tracing, follow, copy, _reveal, clear).Padding(16, 8);
        _timer.Tick += (_, _) => Trace()?.Poll(read: Tracing);

        _empty = new ContentControl { HorizontalContentAlignment = HorizontalAlignment.Center, VerticalContentAlignment = VerticalAlignment.Center, IsTabStop = false };
        var content = UI.ZStack(_scroll, _empty);
        var page = UI.VStack(0, bar, content.Grow().Fill());
        page.KeyboardAccelerators.Add(find);
        page.Loaded += (_, _) => Watch();
        page.Unloaded += (_, _) => Unwatch();
        return page;
    }

    Stack? _whichRow;

    /// Another of the three: the show engine, the setup service, the DMX trace.
    void Choose(int which)
    {
        _which = which;
        if (_whichRow is not null)
            foreach (var b in _whichRow.Children.OfType<ToggleButton>()) b.IsChecked = b.Tag is int i && i == which;
        Watch();
    }

    /// Follows the chosen process's log, or the trace, while the page is on screen.
    void Watch()
    {
        Unwatch();
        if (!Tracing)
        {
            _watching = Proc;
            _watching.LogChanged += Sync;
        }
        var t = Trace();
        _watchingTrace = true;
        if (t is not null)
        {
            t.Changed += Sync;
            t.Poll(read: Tracing);
        }
        // the file's end four times a second while it shows; else only the switch
        _timer.Interval = TimeSpan.FromMilliseconds(Tracing ? 250 : 1000);
        _timer.Start();
        if (_filterBox is not null) _filterBox.PlaceholderText = Tracing ? L("Filter (a fixture, a channel, U1.017)") : L("Filter");
        _reveal?.Visible(Tracing);
        _shown.Clear();
        Sync();
    }

    void Unwatch()
    {
        _timer.Stop();
        if (_watching is not null) _watching.LogChanged -= Sync;
        _watching = null;
        _watchingTrace = false;
        if (_trace is not null) _trace.Changed -= Sync;
    }

    void Sync()
    {
        var trace = Trace();
        if (_tracing is not null && _tracing.IsChecked != (trace?.IsOn == true)) _tracing.IsChecked = trace?.IsOn == true;
        IReadOnlyList<EngineProcess.LogLine> log = Tracing ? trace?.Lines ?? [] : Proc.Log;
        var empty = log.Count == 0;
        if (_empty is ContentControl e)
        {
            var state = !empty ? "" : !Tracing ? "log" : trace?.IsOn == true ? "on" : "off";
            if (!Equals(e.Tag, state))  // not made again four times a second
            {
                e.Tag = state;
                e.Content = state switch
                {
                    "log" => UI.Unavailable("terminal", EngineLog.Empty(_which == 0), EngineLog.EmptyDetail(_which == 0)),
                    "on" => UI.Unavailable("waveform.path", L("Nothing Sent Yet"),
                        L("Start a show or light a fixture: every DMX value that goes out appears here as it changes, with its time, fixture and channel.")),
                    "off" => UI.Unavailable("waveform.path", L("The DMX Trace Is Off"),
                        L("Switched on, every DMX value that goes out to the lights is written down as it changes: when, to which fixture, on which channel. It can be switched on and off while a show runs."),
                        UI.Button(L("Trace DMX"), () => Trace()?.Set(true))),
                    _ => null,
                };
            }
            e.Visible(empty);
        }
        _scroll.Visible(!empty);
        var change = Tracing ? EngineLog.Sync(_shown, EngineLog.Trace(log, _filter), "") : EngineLog.Sync(_shown, log, _filter);
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
            var trace = line.Date == default;  // a DMX trace line: its time is in its text, to the millisecond
            time.Visible(!trace);
            time.Text = trace ? "" : line.Date.ToString("T", CultureInfo.CurrentCulture);
            text.Text = line.Text;
            text.Foreground = ShowUI.Brush(trace ? EngineLog.TraceTone(line) : EngineLog.Tone(line));
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
