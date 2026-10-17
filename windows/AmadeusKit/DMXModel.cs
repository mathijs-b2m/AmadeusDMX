// DMX Devices & Output, the model behind the window (mac/Sources/AmadeusDMX/DMX/DMXWindow.swift DMXModel): your DMX
// devices (Art-Net and sACN nodes, USB interfaces), apart from the sets, and where each universe of the selected
// set goes: which device, which of its outputs. Replace a node or play the set somewhere else: only the mapping
// changes (amadeus/dmx/devices.py).
namespace AmadeusKit;

public sealed class DMXModel : Observable
{
    public readonly record struct Route(string? Device, int Output);

    List<DMXDevice> _devices = [];
    IReadOnlyList<USBInterface> _usb = [];
    IReadOnlyList<ArtNetNode> _nodes = [];
    IReadOnlyList<(int Universe, int Fixtures)> _universes = [];
    Dictionary<int, Route> _routes = [];
    string? _legacy, _selection, _message;
    bool _loading, _saving, _searching, _changed;
    IReadOnlyList<string> _problems = [];

    public IReadOnlyList<DMXDevice> Devices => _devices;
    public IReadOnlyList<USBInterface> Usb { get => _usb; private set => Set(ref _usb, value); }
    public IReadOnlyList<ArtNetNode> Nodes { get => _nodes; private set => Set(ref _nodes, value); }
    public IReadOnlyList<(int Universe, int Fixtures)> Universes { get => _universes; private set => Set(ref _universes, value); }
    /// The set's own output, when it has no device mapping yet.
    public string? Legacy { get => _legacy; private set => Set(ref _legacy, value); }
    public string? Selection { get => _selection; set => Set(ref _selection, value); }
    public bool Loading { get => _loading; private set => Set(ref _loading, value); }
    public bool Saving { get => _saving; private set => Set(ref _saving, value); }
    public bool Searching { get => _searching; private set => Set(ref _searching, value); }
    public string? Message { get => _message; set => Set(ref _message, value); }
    public IReadOnlyList<string> Problems { get => _problems; private set => Set(ref _problems, value); }
    public bool HasChanges { get => _changed; private set => Set(ref _changed, value); }

    Dictionary<string, JSONValue> _layout = [];
    string _set = "", _rig = "";

    /// The set (on the rig) whose universes are routed.
    public string SetName => _set;

    /// Reads your devices and the set's universes. `legacyOutput`: the set's output in words (SetSummary.OutputText).
    public async Task Load(SetupAPI api, string set, string rig, string? legacyOutput)
    {
        _set = set; _rig = rig;
        if (set.Length == 0) return;
        Loading = true;
        try
        {
            var d = await api.DmxDevices();
            _devices = [.. d.Devices];
            Usb = d.Usb;
            _layout = await api.Rig(rig.Length == 0 ? null : rig, set);
            ReadLayout(_layout, legacyOutput);
            if (Selection is null) Selection = _devices.FirstOrDefault()?.Id;
            HasChanges = false;
            Message = null;
            Problems = [];
            Changed(nameof(Devices));
        }
        catch (Exception e) when (e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException)
        {
            Message = e.Message;
        }
        finally { Loading = false; }
    }

    /// The universes and their fixture counts, and the routes, from a set on a rig.
    public void ReadLayout(IReadOnlyDictionary<string, JSONValue> layout, string? legacyOutput)
    {
        _layout = new Dictionary<string, JSONValue>(layout);
        var counts = new SortedDictionary<int, int>();
        foreach (var f in SetLayout.Fixtures(layout))
        {
            var u = Patch.Universe(f);
            counts[u] = counts.GetValueOrDefault(u) + 1;
        }
        Universes = counts.Select(p => (p.Key, p.Value)).ToList();
        _routes = [];
        if (layout.GetValueOrDefault("dmx")?.Object is { } dmx)
        {
            Legacy = null;
            foreach (var (k, v) in dmx)
            {
                if (!int.TryParse(k, System.Globalization.NumberStyles.Integer, System.Globalization.CultureInfo.InvariantCulture, out var u)
                    || v.Object is not { } m) continue;
                _routes[u] = new Route(m.GetValueOrDefault("device")?.String, m.GetValueOrDefault("output")?.Number is { } o ? (int)o : 1);
            }
        }
        else
        {
            Legacy = legacyOutput;
        }
        Changed(nameof(Route));
    }

    /// Where a set universe goes (not mapped: nowhere, its own number as the output).
    public Route RouteOf(int universe) => _routes.TryGetValue(universe, out var r) ? r : new Route(null, universe);

    public void SetRoute(int universe, Route r)
    {
        _routes[universe] = r;
        HasChanges = true;
        Changed(nameof(Route));
    }

    public DMXDevice? Device(string? id) => id is null ? null : _devices.FirstOrDefault(d => d.Id == id);

    /// Where a set universe ends up, in the device's own numbering.
    public string? Target(int universe)
    {
        var r = RouteOf(universe);
        if (Device(r.Device) is not { } d) return null;
        return d.Type switch
        {
            "enttec_pro" => "USB output",
            "sacn" => $"sACN universe {(d.FirstUniverse ?? 1) + r.Output - 1}",
            _ => $"Art-Net universe {(d.FirstUniverse ?? 0) + r.Output - 1}",
        };
    }

    // MARK: devices

    public void Add(DMXDevice d)
    {
        var n = 1;
        var baseId = d.Id;
        while (_devices.Any(x => x.Id == d.Id)) { n++; d.Id = $"{baseId}-{n}"; }
        _devices.Add(d);
        Selection = d.Id;
        DevicesChanged();
    }

    /// The menu's new devices.
    public static DMXDevice NewArtNet() => new("node", "Art-Net node", "artnet") { Ip = "2.0.0.10", FirstUniverse = 0, Outputs = 2 };
    public static DMXDevice NewSACN() => new("sacn", "sACN", "sacn") { FirstUniverse = 1, Priority = 100, Outputs = 4 };
    public static DMXDevice NewUSB() => new("usb", "USB DMX interface", "enttec_pro") { Port = "auto" };

    public void AddNode(ArtNetNode n) =>
        Add(new DMXDevice(Slug(n.Name), n.LongName is { Length: > 0 } l ? l : n.Name, "artnet")
        {
            Ip = n.Ip, FirstUniverse = 0, Outputs = n.Outputs ?? 2,
        });

    public void AddUSB(USBInterface i) =>
        Add(new DMXDevice("usb", i.Description is { Length: > 0 } d ? d : "USB DMX interface", "enttec_pro")
        {
            Port = "auto", Serial = i.WidgetSerial,
        });

    public void Remove(string id)
    {
        _devices.RemoveAll(d => d.Id == id);
        foreach (var (u, r) in _routes.ToList())
            if (r.Device == id) _routes[u] = new Route(null, r.Output);
        Selection = _devices.FirstOrDefault()?.Id;
        DevicesChanged();
        Changed(nameof(Route));
    }

    /// A device's settings were edited (DeviceEditor changes the DMXDevice in place).
    public void DevicesChanged()
    {
        HasChanges = true;
        Changed(nameof(Devices));
    }

    /// Nodes found on the network that aren't among your devices yet.
    public IReadOnlyList<ArtNetNode> FoundNodes => Nodes.Where(n => !_devices.Any(d => d.Ip == n.Ip)).ToList();

    /// DMX USB Pro interfaces plugged in that aren't among your devices yet.
    public IReadOnlyList<USBInterface> FoundUSB => Usb.Where(i => i.IsPro)
        .Where(i => !_devices.Any(d => d.Type == "enttec_pro" && (d.Serial is null || d.Serial == i.WidgetSerial))).ToList();

    public async Task Search(SetupAPI api)
    {
        Searching = true;
        try
        {
            try { Nodes = await api.Discover(); }
            catch (Exception e) when (IsApiError(e)) { Nodes = []; }
            try { Usb = (await api.DmxDevices()).Usb; }
            catch (Exception e) when (IsApiError(e)) { }
            Message = Nodes.Count == 0 && Usb.Count == 0 ? "Nothing answered: is the node on the same network (and switched on)?" : null;
        }
        finally { Searching = false; }
    }

    /// The set's "dmx" block: the routes to devices you have.
    public Dictionary<string, JSONValue> DmxBlock()
    {
        var dmx = new Dictionary<string, JSONValue>();
        foreach (var (u, r) in _routes.OrderBy(p => p.Key))
            if (r.Device is { } id && Device(id) is not null)
                dmx[u.ToString(System.Globalization.CultureInfo.InvariantCulture)] =
                    JSONValue.Of(new Dictionary<string, JSONValue> { ["device"] = id, ["output"] = r.Output });
        return dmx;
    }

    /// Saves your devices, then the set's mapping. True when both were saved (the sets should be read again).
    public async Task<bool> Save(SetupAPI api, bool showRunning)
    {
        Saving = true;
        try
        {
            Problems = await api.SaveDMXDevices(_devices);
            if (Problems.Count > 0) return false;
            _layout["dmx"] = JSONValue.Of(DmxBlock());
            var result = await api.SaveRig(_layout, _rig.Length == 0 ? null : _rig, _set);
            Problems = result.Problems ?? [];
            if (Problems.Count > 0) return false;
            Legacy = null;
            HasChanges = false;
            Message = showRunning ? "Saved. The show uses it from its next start." : "Saved.";
            return true;
        }
        catch (Exception e) when (IsApiError(e))
        {
            Message = e.Message;
            return false;
        }
        finally { Saving = false; }
    }

    static bool IsApiError(Exception e) =>
        e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException;

    /// "NET-2/3 Pocket" → "net-2-3-pocket": an id from a name.
    public static string Slug(string s)
    {
        var t = new string(s.ToLowerInvariant().Select(c => char.IsLetterOrDigit(c) ? c : '-').ToArray());
        var o = string.Join("-", t.Split('-', StringSplitOptions.RemoveEmptyEntries));
        return o.Length == 0 ? "device" : o;
    }
}
