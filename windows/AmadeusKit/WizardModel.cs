// The setup wizard's state (mac/Sources/AmadeusDMX/Wizard/WizardModel.swift): 1. a set (where the DMX goes, then
// your fixtures), 2. a rig (the venue: a new one from a template, or one you have), 3. the set placed on the rig
// (auto-mounted, or by hand in the rig editor). Everything is made through the engine's setup API. In the kit so
// the steps' rules are tested; the app is the IWizardHost.
using System.Text.RegularExpressions;

namespace AmadeusKit;

public sealed record PlannedFixture(CatalogEntry Entry, IReadOnlyList<string> Modes)
{
    public Guid Id { get; } = Guid.NewGuid();
    public string Mode { get; set; } = Modes.FirstOrDefault() ?? "";
    public int Count { get; set; } = 1;
    public IReadOnlyDictionary<string, int> Channels { get; init; } = new Dictionary<string, int>();  // mode → channels (empty: not known)

    public int Footprint => Channels.GetValueOrDefault(Mode);
}

public enum WizardStep { Welcome, Engine, Network, Fixtures, Rig, Director, Review, Done }

public static class WizardSteps
{
    public static readonly WizardStep[] All = Enum.GetValues<WizardStep>();

    public static string Title(this WizardStep s) => s switch
    {
        WizardStep.Welcome => "Welcome",
        WizardStep.Engine => "Engine",
        WizardStep.Fixtures => "Your Fixtures",
        WizardStep.Network => "DMX Output",
        WizardStep.Rig => "Rig",
        WizardStep.Director => "Director",
        WizardStep.Review => "Review",
        _ => "Done",
    };

    /// -wizardStep network (testing): by its title or its name.
    public static WizardStep? Parse(string? raw) =>
        raw is null ? null : All.Cast<WizardStep?>().FirstOrDefault(s => s!.Value.Title().ToLowerInvariant() == raw || s.Value.ToString().ToLowerInvariant() == raw.ToLowerInvariant());
}

/// What the wizard needs from the app.
public interface IWizardHost
{
    SetupAPI Api { get; }
    Task<bool> EnsureSetupService();
    IReadOnlyList<SetSummary> Sets { get; }
    IReadOnlyList<RigSummary> Rigs { get; }
    void ReloadSets();
    /// The workspace (Save and Close reads the new set's composed file from it).
    Workspace? Workspace { get; }
    /// Opens a set on the Sets page.
    void Edit(string set);
    /// The new set on its rig becomes the show's.
    void Select(string rig, string set);
}

public sealed class WizardModel : Observable
{
    WizardStep _step = WizardStep.Welcome;
    public WizardStep Step { get => _step; set { if (Set(ref _step, value)) Changed(nameof(CanContinue)); } }

    // the set: fixtures
    readonly List<PlannedFixture> _planned = [];
    public IReadOnlyList<PlannedFixture> Planned => _planned;
    string _query = "";
    public string Query { get => _query; set => Set(ref _query, value); }
    IReadOnlyList<CatalogEntry> _results = [];
    public IReadOnlyList<CatalogEntry> Results { get => _results; set => Set(ref _results, value); }
    bool _searching;
    public bool Searching { get => _searching; private set => Set(ref _searching, value); }

    // network
    public enum Output { Visualiser, Node, Manual, Usb }
    Output _output = Output.Visualiser;
    public Output OutputKind { get => _output; set { if (Set(ref _output, value)) OutputChanged(); } }
    /// Network nodes: Art-Net or sACN (a Showtec NET-2/3 or NET-2/5 speaks both)
    bool _sacn, _multicast = true;
    public bool Sacn { get => _sacn; set { if (Set(ref _sacn, value)) OutputChanged(); } }
    public bool Multicast { get => _multicast; set { if (Set(ref _multicast, value)) OutputChanged(); } }
    IReadOnlyList<USBInterface> _usb = [];
    public IReadOnlyList<USBInterface> Usb { get => _usb; private set { if (Set(ref _usb, value)) OutputChanged(); } }
    string _usbPort = "auto";
    public string UsbPort { get => _usbPort; set { if (Set(ref _usbPort, value)) OutputChanged(); } }
    bool _searchingUSB;
    public bool SearchingUSB { get => _searchingUSB; private set => Set(ref _searchingUSB, value); }
    IReadOnlyList<ArtNetNode> _nodes = [];
    public IReadOnlyList<ArtNetNode> Nodes { get => _nodes; private set => Set(ref _nodes, value); }
    IReadOnlyList<ArtNetNode> _chosenNodes = [];
    /// The nodes the set plays on, in the order its universes go to them (several: one after the other).
    public IReadOnlyList<ArtNetNode> ChosenNodes { get => _chosenNodes; set { if (Set(ref _chosenNodes, value)) OutputChanged(); } }
    public ArtNetNode? Node => ChosenNodes.FirstOrDefault();
    string _manualIP = "2.0.0.10";
    public string ManualIP { get => _manualIP; set { if (Set(ref _manualIP, value)) OutputChanged(); } }
    bool _discovering;
    public bool Discovering { get => _discovering; private set => Set(ref _discovering, value); }
    string? _discoverError;
    public string? DiscoverError { get => _discoverError; private set => Set(ref _discoverError, value); }

    // the rig: a new one from a template, or one there is already; and how the set goes on it
    bool _useExistingRig;
    public bool UseExistingRig { get => _useExistingRig; set { if (Set(ref _useExistingRig, value)) Changed(nameof(CanContinue)); } }
    string _existingRig = "";
    public string ExistingRig { get => _existingRig; set { if (Set(ref _existingRig, value)) Changed(nameof(CanContinue)); } }
    RigTemplate _template = RigTemplate.Club;
    public RigTemplate Template { get => _template; set { if (Set(ref _template, value)) ApplyTemplate(); } }
    string _rigName = "club";
    public string RigName { get => _rigName; set { if (Set(ref _rigName, value)) Changed(nameof(CanContinue)); } }
    double _width = 10, _height = 4.5, _depth = 15;
    public double Width { get => _width; set => Set(ref _width, value); }
    public double Height { get => _height; set => Set(ref _height, value); }
    public double Depth { get => _depth; set => Set(ref _depth, value); }
    bool _ledWall = true, _autoMount = true;
    public bool LedWall { get => _ledWall; set => Set(ref _ledWall, value); }
    public bool AutoMount { get => _autoMount; set => Set(ref _autoMount, value); }

    // director
    IReadOnlyList<DirectorOption> _directors = [];
    public IReadOnlyList<DirectorOption> Directors { get => _directors; set => Set(ref _directors, value); }
    string _director = "rules";
    public string Director { get => _director; set => Set(ref _director, value); }

    // create
    string _name = "my-set";
    public string Name { get => _name; set { if (Set(ref _name, value)) Changed(nameof(CanContinue)); } }
    bool _creating;
    public bool Creating { get => _creating; private set => Set(ref _creating, value); }
    string _progress = "";
    public string Progress { get => _progress; private set => Set(ref _progress, value); }
    string? _error;
    public string? Error { get => _error; set => Set(ref _error, value); }

    public WizardModel(Defaults? defaults = null)
    {
        ApplyTemplate();
        if (WizardSteps.Parse((defaults ?? Defaults.Standard).String("wizardStep")) is { } st)  // -wizardStep network (testing)
        {
            Step = st;
            if (st == WizardStep.Network) OutputKind = Output.Usb;
        }
    }

    void ApplyTemplate()
    {
        (Width, Height, Depth) = Template.Size();
        LedWall = Template is RigTemplate.Club or RigTemplate.Stage;
        if (RigTemplates.IsDefaultName(RigName)) RigName = Template.RawValue();
    }

    void OutputChanged() => Changed(nameof(CanContinue), nameof(OutputText), nameof(ArtnetIP), nameof(Node), nameof(UniversesAvailable), nameof(HasSomethingToSave));

    public int FixtureCount => _planned.Sum(p => p.Count);

    public bool CanContinue => Step switch
    {
        WizardStep.Fixtures => _planned.Count > 0,
        WizardStep.Rig => UseExistingRig ? ExistingRig.Length > 0 : RigName.Trim().Length > 0,
        WizardStep.Network => (OutputKind != Output.Node || ChosenNodes.Count > 0) && (OutputKind != Output.Usb || Usb.Count > 0 || UsbPort == "auto"),
        WizardStep.Review => Name.Trim().Length > 0,
        _ => true,
    };

    /// The step after this one: past the engine when it's there already and you have sets (a new set, not the
    /// first launch).
    public WizardStep NextStep(bool engineValid, bool hasSets)
    {
        var s = Step == WizardStep.Done ? WizardStep.Done : Step + 1;
        if (s == WizardStep.Engine && engineValid && Step == WizardStep.Welcome && hasSets) s = WizardStep.Network;
        return s;
    }

    public WizardStep PreviousStep => Step == WizardStep.Welcome ? WizardStep.Welcome : Step - 1;

    // MARK: the planned fixtures

    public void Remove(PlannedFixture p)
    {
        _planned.RemoveAll(x => x.Id == p.Id);
        PlannedChanged();
    }

    public void PlannedChanged() => Changed(nameof(Planned), nameof(FixtureCount), nameof(CanContinue), nameof(UniversesNeeded), nameof(HasSomethingToSave));

    // MARK: catalogue

    public async Task Search(SetupAPI api)
    {
        var q = Query.Trim();
        if (q.Length < 2) { Results = []; return; }
        Searching = true;
        try { Results = await api.Catalog(q, 30); }
        catch (Exception e) when (IsApiError(e)) { Results = []; }
        finally { Searching = false; }
    }

    public async Task Add(CatalogEntry e, SetupAPI api)
    {
        var channels = e.Modes?.ToDictionary() ?? [];
        if (channels.Count == 0)
        {
            try
            {
                foreach (var m in (await api.Details(e.Key)).ModeList) channels.TryAdd(m.Name, m.Channels);
            }
            catch (Exception x) when (IsApiError(x)) { }
        }
        var modes = channels.OrderByDescending(p => p.Value).Select(p => p.Key).ToList();
        _planned.Add(new PlannedFixture(e, modes) { Count = e.Type == "moving head" ? 4 : 2, Channels = channels });
        PlannedChanged();
    }

    /// The universes the fixtures take, packed as the engine patches them (amadeus/dmx/discover.py
    /// assign_addresses: a fixture never straddles two universes).
    public int UniversesNeeded
    {
        get
        {
            int u = _planned.Count == 0 ? 0 : 1, next = 1;
            foreach (var p in _planned.Where(p => p.Footprint > 0))
                for (var i = 0; i < p.Count; i++)
                {
                    if (next + p.Footprint - 1 > 512) { u++; next = 1; }
                    next += p.Footprint;
                }
            return u;
        }
    }

    /// How many universes the chosen output carries (null: no limit, or not known).
    public int? UniversesAvailable
    {
        get
        {
            switch (OutputKind)
            {
                case Output.Visualiser or Output.Manual: return null;
                case Output.Usb: return 1;
                default:
                    if (Sacn && Multicast) return null;
                    var outs = ChosenNodes.Select(n => n.Outputs ?? 0).ToList();
                    return outs.Contains(0) || outs.Count == 0 ? null : outs.Sum();
            }
        }
    }

    // MARK: network

    public async Task Discover(SetupAPI api)
    {
        Discovering = true;
        DiscoverError = null;
        try
        {
            Nodes = await api.Discover();
            if (ChosenNodes.Count == 0 && Nodes.FirstOrDefault() is { } first) ChosenNodes = [first];
            if (Nodes.Count == 0) DiscoverError = "No Art-Net nodes answered. Check the cable and that the node is powered.";
        }
        catch (Exception e) when (IsApiError(e)) { DiscoverError = e.Message; }
        finally { Discovering = false; }
    }

    public async Task FindUSB(SetupAPI api)
    {
        SearchingUSB = true;
        try
        {
            try { Usb = await api.UsbInterfaces(); }
            catch (Exception e) when (IsApiError(e)) { Usb = []; }
            if (Usb.FirstOrDefault(u => u.IsPro) is { } pro) UsbPort = pro.Port;
        }
        finally { SearchingUSB = false; }
    }

    /// The set's "output" block (nil: Art-Net to `ArtnetIP`, as sets always did).
    public Dictionary<string, JSONValue>? OutputSpec
    {
        get
        {
            switch (OutputKind)
            {
                case Output.Visualiser: return null;
                case Output.Usb: return new() { ["type"] = "enttec_pro", ["port"] = UsbPort, ["universe"] = 1 };
                default:
                    if (!Sacn) return null;
                    var s = new Dictionary<string, JSONValue> { ["type"] = "sacn", ["priority"] = 100 };
                    if (!Multicast) s["ip"] = ArtnetIP;
                    return s;
            }
        }
    }

    public string OutputText => OutputKind switch
    {
        Output.Visualiser => "Visualiser only",
        Output.Usb => $"USB ENTTEC Pro → {(UsbPort == "auto" ? "first one found" : RigFile.LastPathComponent(UsbPort))}",
        Output.Node when ChosenNodes.Count > 1 =>
            $"{(Sacn ? "sACN" : "Art-Net")} → {ChosenNodes.Count} nodes ({string.Join(", ", ChosenNodes.Select(n => n.Ip))})",
        _ => Sacn ? $"sACN → {(Multicast ? "multicast" : ArtnetIP)}" : $"Art-Net → {ArtnetIP}",
    };

    public string ArtnetIP => OutputKind switch
    {
        Output.Node => Node?.Ip ?? "127.0.0.1",
        Output.Manual => ManualIP,
        _ => "127.0.0.1",
    };

    // MARK: create: the set, the rig, the set on the rig

    /// "My Club!" → "my-club": a name the engine takes as a file name.
    public static string Safe(string name) =>
        Regex.Replace(name.ToLowerInvariant(), "[^a-z0-9_-]+", "-").Trim('-');

    public async Task Create(IWizardHost host)
    {
        Creating = true;
        Error = null;
        var api = host.Api;
        var setName = Safe(Name);
        var rig = UseExistingRig ? ExistingRig : Safe(RigName);
        try
        {
            Progress = "Starting the engine’s setup service…";
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            if (host.Sets.Any(s => s.Name == setName))
                throw SetupAPIException.Server($"A set called “{setName}” already exists. Choose another name.");
            if (!UseExistingRig && host.Rigs.Any(r => r.Name == rig))
                throw SetupAPIException.Server($"A rig called “{rig}” already exists. Choose another name, or use it.");
            Progress = "1/3 · The set…";
            await api.CreateSet(setName);
            Progress = "2/3 · The rig…";
            if (UseExistingRig) await api.MakeDefaultRig(rig);
            else await api.CreateRig(rig, Template.RawValue(), Width, Height, Depth, LedWall);
            var layout = await api.Rig(rig, setName);
            var items = new List<JSONValue>();
            foreach (var p in _planned)
            {
                Progress = $"Adding {p.Count}× {p.Entry.Model}…";
                var key = p.Entry.IsLocal ? p.Entry.Key : await api.AddToLibrary(p.Entry.Key);
                for (var i = 0; i < p.Count; i++)
                    items.Add(JSONValue.Of(new Dictionary<string, JSONValue> { ["fixture"] = key, ["mode"] = p.Mode, ["universe"] = 1 }));
            }
            Progress = "Patching addresses…";
            Compose(layout, await Autopatch(api, items));
            if (OutputKind != Output.Visualiser)
            {
                Progress = "Adding your DMX devices…";
                if (await AddDevices(api, Universes(layout.GetValueOrDefault("fixtures")?.Array ?? [])) is { } dmx)
                    layout["dmx"] = JSONValue.Of(dmx);
            }
            await api.SaveRig(layout, rig, setName);
            if (AutoMount)
            {
                Progress = $"3/3 · Mounting the fixtures on {rig}…";
                await api.Automount(rig, setName);
            }
            host.ReloadSets();
            host.Select(rig, setName);
            Name = setName;
            RigName = rig;
            Step = WizardStep.Done;
        }
        catch (Exception e) when (IsApiError(e)) { Error = e.Message; }
        finally
        {
            Creating = false;
            Progress = "";
        }
    }

    /// The new set's layout: the patched fixtures (without the places autopatch gave them: the rig decides those),
    /// where the DMX goes, the director and a description.
    public void Compose(Dictionary<string, JSONValue> layout, IReadOnlyList<JSONValue> patched)
    {
        var placement = RigDocument.PlacementKeys.ToHashSet();
        layout["fixtures"] = JSONValue.Of(patched.Select(v => v.Object).OfType<IReadOnlyDictionary<string, JSONValue>>()
            .Select(o => JSONValue.Of(o.Where(p => !placement.Contains(p.Key)))));
        var artnet = layout.GetValueOrDefault("artnet")?.Object is { } a ? new Dictionary<string, JSONValue>(a)
            : new Dictionary<string, JSONValue> { ["port"] = 6454, ["fps"] = 40 };
        artnet["ip"] = ArtnetIP;
        layout["artnet"] = JSONValue.Of(artnet);
        if (OutputSpec is { } spec) layout["output"] = JSONValue.Of(spec); else layout.Remove("output");
        layout["director"] = Director;
        layout["description"] = $"{FixtureCount} fixtures, made with the Windows app";
    }

    /// The chosen output as DMX devices (config/devices.json; one already there is kept), and the set's universes
    /// over their outputs in order: node 1 output 1, output 2, …, then node 2. Returns the set's "dmx" mapping
    /// (null: the visualiser only, nothing to add).
    async Task<Dictionary<string, JSONValue>?> AddDevices(SetupAPI api, IReadOnlyList<int> universes)
    {
        if (OutputKind == Output.Visualiser) return null;
        var devices = (await api.DmxDevices()).Devices.ToList();
        var slots = new List<(string Device, int Output)>();
        // A device there already (same kind, same address), or this one added with a free id.
        DMXDevice Use(DMXDevice d, Func<DMXDevice, bool> same)
        {
            if (devices.FirstOrDefault(same) is { } had) return had;
            var id = d.Id;
            var i = 1;
            while (devices.Any(x => x.Id == d.Id)) { i++; d.Id = $"{id}-{i}"; }
            devices.Add(d);
            return d;
        }
        var count = Math.Max(universes.Count, 1);
        if (OutputKind == Output.Usb)
        {
            var i = Usb.FirstOrDefault(x => x.Port == UsbPort);
            var d = new DMXDevice("usb", i?.Description ?? "USB DMX interface", "enttec_pro") { Port = UsbPort, Serial = i?.WidgetSerial };
            var u = Use(d, x => x.Type == "enttec_pro" && (x.Port == UsbPort || (x.Serial is not null && x.Serial == d.Serial)));
            slots = [(u.Id, 1)];
        }
        else if (Sacn && Multicast)  // a node or an address, sACN multicast: one sender, every sACN node listens
        {
            var d = new DMXDevice("sacn", "sACN multicast", "sacn") { FirstUniverse = 1, Priority = 100, Outputs = count };
            var u = Use(d, x => x.Type == "sacn" && x.Ip is null);
            slots = [.. Enumerable.Range(1, Math.Max(count, u.OutputCount)).Select(o => (u.Id, o))];
        }
        else if (OutputKind == Output.Manual)
        {
            var d = new DMXDevice("node", $"Node {ManualIP}", Sacn ? "sacn" : "artnet")
            {
                Ip = ManualIP, Outputs = Math.Max(count, 2), FirstUniverse = Sacn ? 1 : 0, Priority = Sacn ? 100 : null,
            };
            var u = Use(d, x => x.Type == d.Type && x.Ip == ManualIP);
            slots = [.. Enumerable.Range(1, u.OutputCount).Select(o => (u.Id, o))];
        }
        else
        {
            foreach (var n in ChosenNodes)
            {
                var d = new DMXDevice(DMXModel.Slug(n.Name), n.LongName is { Length: > 0 } l ? l : n.Name, Sacn ? "sacn" : "artnet")
                {
                    Ip = n.Ip, Outputs = n.Outputs ?? 2, FirstUniverse = Sacn ? 1 : n.Universes is { Count: > 0 } us ? us.Min() : 0,
                    Priority = Sacn ? 100 : null,
                };
                var u = Use(d, x => x.Type == d.Type && x.Ip == n.Ip);
                slots.AddRange(Enumerable.Range(1, u.OutputCount).Select(o => (u.Id, o)));
            }
        }
        var problems = await api.SaveDMXDevices(devices);
        if (problems.Length > 0) throw SetupAPIException.Server(string.Join("\n", problems));
        var dmx = new Dictionary<string, JSONValue>();
        foreach (var (u, slot) in universes.Zip(slots))
            dmx[u.ToString(System.Globalization.CultureInfo.InvariantCulture)] =
                JSONValue.Of(new Dictionary<string, JSONValue> { ["device"] = slot.Device, ["output"] = slot.Output });
        return dmx;
    }

    static IReadOnlyList<int> Universes(IEnumerable<JSONValue> fixtures) =>
        [.. fixtures.Select(f => f.Object?.GetValueOrDefault("universe")?.Number).OfType<double>().Select(n => (int)n).Distinct().Order()];

    // MARK: save and close: what is chosen so far, made for real, to go on with on the pages

    /// Whether there is anything to save before the end (an output, fixtures).
    public bool HasSomethingToSave => OutputKind != Output.Visualiser || _planned.Count > 0;

    /// Saves the DMX output as your devices and the fixtures as a set of their own (on no rig yet). Returns what
    /// was saved and where to go on (**bold** as on the Mac), null when it failed (`Error` says why).
    public async Task<string?> SaveAndClose(IWizardHost host)
    {
        Creating = true;
        Error = null;
        var api = host.Api;
        try
        {
            Progress = "Starting the engine’s setup service…";
            if (!await host.EnsureSetupService()) throw SetupAPIException.NotRunningError();
            var saved = new List<string>();
            if (_planned.Count == 0)
            {
                if (OutputKind != Output.Visualiser)
                {
                    Progress = "Adding your DMX devices…";
                    await AddDevices(api, []);
                    saved.Add($"Your DMX output ({OutputText}) is on the **DMX Output** page.");
                }
            }
            else
            {
                var setName = Safe(Name);
                var i = 1;
                while (host.Sets.Any(s => s.Name == setName)) { i++; setName = $"{Safe(Name)}-{i}"; }
                Progress = "The set…";
                await api.CreateSet(setName);
                var items = new List<JSONValue>();
                foreach (var p in _planned)
                {
                    Progress = $"Adding {p.Count}× {p.Entry.Model}…";
                    var key = p.Entry.IsLocal ? p.Entry.Key : await api.AddToLibrary(p.Entry.Key);
                    for (var n = 0; n < p.Count; n++)
                        items.Add(JSONValue.Of(new Dictionary<string, JSONValue> { ["fixture"] = key, ["mode"] = p.Mode, ["universe"] = 1 }));
                }
                Progress = "Patching addresses…";
                var placement = RigDocument.PlacementKeys.ToHashSet();
                var fixtures = (await Autopatch(api, items)).Select(v => v.Object).OfType<IReadOnlyDictionary<string, JSONValue>>()
                    .Select(o => JSONValue.Of(o.Where(p => !placement.Contains(p.Key)))).ToList();
                var layout = host.Workspace?.Composed("", setName) is { } data ? JSONValue.ParseObject(data) ?? [] : [];
                layout["fixtures"] = JSONValue.Of(fixtures);
                layout["description"] = $"{FixtureCount} fixtures, made with the Windows app";
                if (OutputKind != Output.Visualiser)
                {
                    Progress = "Adding your DMX devices…";
                    if (await AddDevices(api, Universes(fixtures)) is { } dmx) layout["dmx"] = JSONValue.Of(dmx);
                }
                await api.SaveSet(layout, setName);
                host.ReloadSets();
                host.Edit(setName);
                saved.Add($"Your set **{setName}** ({FixtureCount} fixtures) is on the **Sets** page"
                          + (OutputKind == Output.Visualiser ? "." : ", its DMX output on the **DMX Output** page."));
                saved.Add("To hang it: the **Rigs** page, pick or make a rig (New Rig…) and **Place a Set**.");
            }
            saved.Add("Or start over any time with **File › New Set…**.");
            return string.Join("\n\n", saved);
        }
        catch (Exception e) when (IsApiError(e))
        {
            Error = e.Message;
            return null;
        }
        finally
        {
            Creating = false;
            Progress = "";
        }
    }

    static async Task<IReadOnlyList<JSONValue>> Autopatch(SetupAPI api, IReadOnlyList<JSONValue> items) =>
        await api.Post("api/autopatch", new Dictionary<string, object> { ["fixtures"] = items },
            c => J.Req(c, "fixtures", J.ArrayOf(JSONValue.From)));

    static bool IsApiError(Exception e) =>
        e is HttpRequestException or SetupAPIException or TaskCanceledException or System.Text.Json.JsonException;
}
