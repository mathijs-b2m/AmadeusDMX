// DMX Devices & Output (Show menu, Ctrl+Shift+D): your DMX devices (Art-Net and sACN nodes, USB interfaces), apart
// from the sets, and where each universe of the selected set goes: which device, which of its outputs. Replace a
// node or play the set somewhere else: only the mapping changes (amadeus/dmx/devices.py). The model is the kit's
// DMXModel (mac/Sources/AmadeusDMX/DMX/DMXWindow.swift).
using Microsoft.UI.Windowing;
using Windows.System;

namespace AmadeusDMX;

public sealed partial class DMXWindow : Window
{
    readonly AppModel _model;
    readonly DMXModel _dmx = new();
    readonly ContentControl _devices = Host(), _found = Host(), _editor = Host();
    readonly ListView _list = new() { SelectionMode = ListViewSelectionMode.Single };
    bool _listing;

    static ContentControl Host() => new()
    {
        HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch, IsTabStop = false,
    };

    public DMXWindow(AppModel model)
    {
        _model = model;
        Title = "DMX Devices & Output";
        var icon = Path.Combine(AppContext.BaseDirectory, "Assets", "AmadeusDMX.ico");
        if (File.Exists(icon)) AppWindow.SetIcon(icon);
        SystemBackdrop = new Microsoft.UI.Xaml.Media.MicaBackdrop();
        var scale = GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;  // Resize is in pixels
        AppWindow.Resize(new Windows.Graphics.SizeInt32((int)(900 * scale), (int)(620 * scale)));
        if (AppWindow.Presenter is OverlappedPresenter p)
        {
            p.PreferredMinimumWidth = 760;
            p.PreferredMinimumHeight = 520;
        }
        Content = Build();
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")]
    static extern uint GetDpiForWindow(IntPtr hwnd);

    FrameworkElement Build()
    {
        var grid = new Grid();
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(340), MinWidth = 300 });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star), MinWidth = 380 });
        var devices = DevicesPane();
        var divider = UI.Divider(vertical: true);
        var universes = UniversesPane();
        Grid.SetColumn(devices, 0);
        Grid.SetColumn(divider, 1);
        Grid.SetColumn(universes, 2);
        grid.Children.Add(devices);
        grid.Children.Add(divider);
        grid.Children.Add(universes);

        // the toolbar: Save (Ctrl+S)
        var save = UI.Button("Save", () => _ = Save()).Prominent().Shortcut(VirtualKey.S)
            .Bind(_dmx, [nameof(DMXModel.HasChanges), nameof(DMXModel.Saving)], b =>
            {
                b.Content = _dmx.Saving ? "Saving…" : "Save";
                b.IsEnabled = _dmx.HasChanges && !_dmx.Saving;
            });
        var bar = UI.HStack(8, UI.Text("DMX Devices & Output", Font.Headline), UI.Spacer(), save).Padding(16, 10);
        var root = new Grid();
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var line = UI.Divider();
        Grid.SetRow(bar, 0);
        Grid.SetRow(line, 1);
        Grid.SetRow(grid, 2);
        root.Children.Add(bar);
        root.Children.Add(line);
        root.Children.Add(grid);
        // the selected set (on its rig): read again whenever it changes (SwiftUI's .task(id:))
        root.Bind(_model, [nameof(AppModel.SelectedSet), nameof(AppModel.SelectedRig)], g => { _ = Load(); });
        return root;
    }

    async Task Load()
    {
        if (!await _model.EnsureSetupService()) { _dmx.Message = SetupAPIException.NotRunningError().Message; return; }
        await _dmx.Load(_model.Api, _model.SelectedSet, _model.SelectedRig, _model.CurrentSet?.OutputText);
        ShowEditor();
    }

    async Task Save()
    {
        if (await _dmx.Save(_model.Api, _model.EngineRunning)) _model.ReloadSets();
    }

    // MARK: your devices

    FrameworkElement DevicesPane()
    {
        var add = UI.MenuButton(UI.Label("plus", "Add"), () => UI.Menu(
            UI.Item("Art-Net Node", () => _dmx.Add(DMXModel.NewArtNet())),
            UI.Item("sACN Node / Multicast", () => _dmx.Add(DMXModel.NewSACN())),
            UI.Item("USB Interface", () => _dmx.Add(DMXModel.NewUSB()))));
        var search = UI.Button("Search", () => _ = _dmx.Search(_model.Api), "antenna.radiowaves.left.and.right")
            .Tooltip("Look for Art-Net nodes on the network and USB DMX interfaces on this computer")
            .Bind(_dmx, nameof(DMXModel.Searching), b =>
            {
                b.Content = UI.Label("antenna.radiowaves.left.and.right", _dmx.Searching ? "Searching…" : "Search");
                b.IsEnabled = !_dmx.Searching;
            });
        var header = UI.HStack(8, UI.Text("Your DMX Devices", Font.Headline), UI.Spacer(), add, search).Padding(12);

        _list.SelectionChanged += (_, _) =>
        {
            if (_listing) return;
            if (_list.SelectedItem is ListViewItem { Tag: string id } && id != _dmx.Selection) _dmx.Selection = id;
        };
        _devices.Content = _list;
        _devices.Bind(_dmx, [nameof(DMXModel.Devices), nameof(DMXModel.Selection)], _ => ListDevices());
        _found.Bind(_dmx, [nameof(DMXModel.Devices), nameof(DMXModel.Nodes), nameof(DMXModel.Usb)], c => c.Content = Found());
        // the editor follows the selection only: rebuilt while you type a name, it would lose the focus
        _editor.Bind(_dmx, nameof(DMXModel.Selection), _ => ShowEditor());

        var lists = UI.VStack(8,
            UI.Text("Devices", Font.Subheadline).Secondary().Bold().Margin(12, 0, 0, 0),
            _devices,
            _found);
        var grid = new Grid();
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var scroll = UI.Scroll(lists);
        var editor = UI.Scroll(_editor).MaxHeight(320);
        Grid.SetRow(header, 0);
        Grid.SetRow(scroll, 1);
        Grid.SetRow(editor, 2);
        grid.Children.Add(header);
        grid.Children.Add(scroll);
        grid.Children.Add(editor);
        return grid;
    }

    void ListDevices()
    {
        _listing = true;
        try
        {
            _list.Items.Clear();
            foreach (var d in _dmx.Devices)
                _list.Items.Add(new ListViewItem
                {
                    Tag = d.Id,
                    Content = UI.VStack(2, UI.Text(d.Name), UI.Text($"{d.KindText} · {d.AddressText}", Font.Caption).Secondary()).Padding(0, 4),
                });
            if (_dmx.Devices.Count == 0)
                _list.Items.Add(new ListViewItem
                {
                    Content = UI.Text("No devices yet: add one, or search the network.").Secondary().Wrap(), IsEnabled = false,
                });
            _list.SelectedItem = _list.Items.OfType<ListViewItem>().FirstOrDefault(i => i.Tag as string == _dmx.Selection);
        }
        finally { _listing = false; }
    }

    UIElement? Found()
    {
        var nodes = _dmx.FoundNodes;
        var usb = _dmx.FoundUSB;
        if (nodes.Count == 0 && usb.Count == 0) return null;
        var rows = new List<UIElement?>();
        foreach (var n in nodes)
            rows.Add(Form.Row(UI.VStack(2, UI.Text(n.LongName is { Length: > 0 } l ? l : n.Name),
                                         UI.Text($"Art-Net · {n.Ip} · {n.Outputs ?? 0} outputs", Font.Caption).Secondary()),
                              UI.Button("Add", () => _dmx.AddNode(n))));
        foreach (var i in usb)
            rows.Add(Form.Row(UI.VStack(2, UI.Text(i.Description ?? "USB DMX interface"),
                                         UI.Text($"USB · {i.Port}", Font.Caption).Secondary()),
                              UI.Button("Add", () => _dmx.AddUSB(i))));
        return Form.Section("Found", rows).Padding(12, 0);
    }

    void ShowEditor()
    {
        _editor.Content = _dmx.Device(_dmx.Selection) is { } d
            ? new DeviceEditor(d, _dmx.Usb, _dmx.DevicesChanged, () => _dmx.Remove(d.Id)).Build().Padding(12)
            : null;
    }

    // MARK: the set's universes

    FrameworkElement UniversesPane()
    {
        var live = UI.Live(_dmx, Universes, nameof(DMXModel.Universes), "Route", nameof(DMXModel.Devices), nameof(DMXModel.Legacy),
                           nameof(DMXModel.Problems), nameof(DMXModel.Message), nameof(DMXModel.Loading));
        return UI.Scroll(live.Bind(_model, nameof(AppModel.SelectedSet), c => c.Content = Universes()));
    }

    UIElement Universes()
    {
        var rows = new List<UIElement?>();
        var none = new DMXDevice("", "Not sent", "");
        foreach (var (universe, fixtures) in _dmx.Universes)
        {
            var r = _dmx.RouteOf(universe);
            var choices = new List<DMXDevice> { none };
            choices.AddRange(_dmx.Devices);
            var device = UI.Picker(choices, _dmx.Device(r.Device) ?? none, d => d.Name,
                d => _dmx.SetRoute(universe, new DMXModel.Route(d.Id.Length == 0 ? null : d.Id, r.Output)));
            UIElement? output = null;
            if (_dmx.Device(r.Device) is { OutputCount: > 1 } dev)
                output = UI.Picker(Enumerable.Range(1, dev.OutputCount).ToList(), r.Output, o => $"Output {o}",
                    o => _dmx.SetRoute(universe, new DMXModel.Route(r.Device, o)));
            var detail = $"{fixtures} fixture{(fixtures == 1 ? "" : "s")}" + (_dmx.Target(universe) is { } t ? $" · {t}" : "");
            rows.Add(Form.Row(Form.Labeled($"Universe {universe}", detail), UI.HStack(8, device, output)));
        }
        if (_dmx.Universes.Count == 0 && !_dmx.Loading)
            rows.Add(UI.Text("This set has no fixtures yet.").Secondary());
        return UI.VStack(12,
            UI.VStack(4,
                UI.Text($"Set “{_model.SelectedSet}”", Font.Headline),
                UI.Text("Where each universe of the set goes. Change the devices or the venue: only this changes, the patch stays.", Font.Callout)
                    .Secondary().Wrap()),
            _dmx.Legacy is { } legacy
                ? Form.Note("info.circle", $"Now: {legacy} (the set’s own settings). Choose a device per universe to use your devices instead.")
                : null,
            Form.Section(null, rows),
            UI.VStack(4, [.. _dmx.Problems.Select(p => (UIElement)Form.Note("exclamationmark.triangle.fill", p, Tint.Orange))]),
            _dmx.Message is { } m ? UI.Text(m, Font.Callout).Secondary().Wrap() : null
        ).Padding(16);
    }
}

/// One device's settings (edited in place; `changed` tells the model).
public sealed class DeviceEditor(DMXDevice device, IReadOnlyList<USBInterface> usb, Action changed, Action remove)
{
    readonly ContentControl _kind = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, IsTabStop = false };

    public FrameworkElement Build()
    {
        var name = UI.Field("Name", device.Name, v => { device.Name = v; changed(); });
        var kinds = new[] { ("artnet", "Art-Net node"), ("sacn", "sACN (E1.31)"), ("enttec_pro", "USB interface (DMX USB Pro)") };
        var kind = UI.Picker(kinds, kinds.FirstOrDefault(k => k.Item1 == device.Type), k => k.Item2, k =>
        {
            device.Type = k.Item1;
            changed();
            _kind.Content = KindRows();
        });
        _kind.Content = KindRows();
        var removeButton = UI.Button("Remove Device", remove).Foreground(Tint.Red);
        return Form.Section(null,
            [
                Form.Row("Name", name.MinWidth(180)),
                Form.Row("Kind", kind),
                _kind,
                UI.HStack(UI.Spacer(), removeButton),
            ]);
    }

    UIElement KindRows()
    {
        var rows = UI.VStack(10);
        switch (device.Type)
        {
            case "enttec_pro":
                var ports = new List<string> { "auto" };
                ports.AddRange(usb.Select(i => i.Port));
                if (device.Port is { } p && !ports.Contains(p)) ports.Add(p);
                rows.Children.Add(Form.Row("Port", UI.Picker(ports, device.Port ?? "auto", x => x == "auto" ? "The first one found" : LastPart(x),
                    x => { device.Port = x; changed(); })));
                break;
            case "sacn":
                var ip = UI.Field("Node IP address", device.Ip ?? "", v => { if (device.Ip is not null) { device.Ip = v; changed(); } });
                var ipRow = Form.Row("Node IP address", ip.MinWidth(160)).Visible(device.Ip is not null);
                rows.Children.Add(Form.Row("Multicast (every sACN node listens)", UI.Toggle("", device.Ip is null, on =>
                {
                    device.Ip = on ? null : "2.0.0.10";
                    ip.Text = device.Ip ?? "";
                    ipRow.Visible(!on);
                    changed();
                })));
                rows.Children.Add(ipRow);
                rows.Children.Add(Form.Stepper(device.Priority ?? 100, 0, 200, v => $"Priority {v}", v => { device.Priority = v; changed(); }, 10));
                Numbering(rows, 1);
                break;
            default:
                rows.Children.Add(Form.Row("Node IP address",
                    UI.Field("Node IP address", device.Ip ?? "", v => { device.Ip = v; changed(); }).MinWidth(160)));
                Numbering(rows, 0);
                break;
        }
        return rows;
    }

    void Numbering(Stack rows, int first)
    {
        rows.Children.Add(Form.Stepper(device.OutputCount, 1, 64, v => $"Outputs: {v}", v => { device.Outputs = v; changed(); }));
        rows.Children.Add(Form.Row("Its first output is", UI.Picker([0, 1], device.FirstUniverse ?? first, u => $"Universe {u}",
                u => { device.FirstUniverse = u; changed(); })
            .Tooltip("How the device counts: most Art-Net nodes call their first output universe 0, sACN starts at 1.")));
    }

    /// "\\.\COM3" → "COM3"
    static string LastPart(string port) => port.TrimEnd('/', '\\').Split('/', '\\').LastOrDefault() is { Length: > 0 } l ? l : port;
}
