// Wizard step 1: where the DMX goes, before the fixtures (Art-Net / sACN nodes, a USB interface or the visualiser only)
// (mac/Sources/AmadeusDMX/Wizard/Steps/NetworkStep.swift).
namespace AmadeusDMX;

public sealed class NetworkStep(AppModel model, WizardModel w)
{
    static readonly (WizardModel.Output Kind, string Title)[] Outputs =
    [
        (WizardModel.Output.Visualiser, "Visualiser only"), (WizardModel.Output.Node, "Network node"),
        (WizardModel.Output.Manual, "Node address"), (WizardModel.Output.Usb, "USB interface"),
    ];

    public UIElement Build()
    {
        var picker = UI.Segmented(Outputs.Select(o => o.Kind).ToList(), w.OutputKind, k => Outputs.First(o => o.Kind == k).Title, k =>
        {
            w.OutputKind = k;
            _ = Find();
        });
        var body = UI.Live(w, Body, nameof(WizardModel.OutputKind), nameof(WizardModel.Sacn), nameof(WizardModel.Nodes),
                           nameof(WizardModel.ChosenNodes), nameof(WizardModel.Discovering), nameof(WizardModel.DiscoverError),
                           nameof(WizardModel.Usb), nameof(WizardModel.UsbPort), nameof(WizardModel.SearchingUSB));
        _ = Find();
        return UI.VStack(16,
            StepHeader.Build("cable.connector", "DMX Output",
                "First where the DMX goes: a network node (Art-Net or sACN) or a USB interface on this computer. Your fixtures come next. No lights here? Run in the visualiser only."),
            picker,
            body);
    }

    /// The first time a kind is shown, look for what it can use (SwiftUI's .task(id: w.output)).
    async Task Find()
    {
        if (w.OutputKind == WizardModel.Output.Node && w.Nodes.Count == 0) await w.Discover(model.Api);
        if (w.OutputKind == WizardModel.Output.Usb && w.Usb.Count == 0) await w.FindUSB(model.Api);
    }

    UIElement Body() => w.OutputKind switch
    {
        WizardModel.Output.Visualiser => Form.Note("eye", "The show runs on screen only. You can add an output later on the DMX Output page.", null, Font.Body),
        WizardModel.Output.Usb => UI.VStack(12, UsbList(), LaterHint()),
        _ => UI.VStack(12, ProtocolPicker(), w.OutputKind == WizardModel.Output.Node ? NodeList()
            : UI.VStack(12, Form.Section(null, [Form.Row("Node IP address", UI.Field("Node IP address", w.ManualIP, v => w.ManualIP = v).MinWidth(180))]),
                        LaterHint())),
    };

    UIElement ProtocolPicker()
    {
        var s = UI.VStack(8, Form.Row(UI.Text("Protocol"),
            Form.Radio([false, true], w.Sacn, v => v ? "sACN (E1.31)" : "Art-Net", v => w.Sacn = v, horizontal: true)));
        if (w.Sacn)
        {
            s.Children.Add(UI.Check("Multicast (every sACN node on the network listens; usual)", w.Multicast, v => w.Multicast = v));
            s.Children.Add(UI.Text("Set the node’s input to sACN too. On a Showtec NET-2/3 or NET-2/5 Pocket: in its menu or web page. Universe 1 = its first output.",
                                   Font.Callout).Secondary().Wrap());
        }
        return s;
    }

    UIElement NodeList()
    {
        var s = UI.VStack(8,
            UI.HStack(8,
                UI.Button(w.Discovering ? "Searching…" : "Search the Network", () => _ = w.Discover(model.Api)).Disabled(w.Discovering),
                w.Discovering ? UI.Spinner() : null),
            w.DiscoverError is { } e ? UI.Text(e, Font.Callout).Secondary().Wrap() : null);
        if (w.Nodes.Count > 1)
            s.Children.Add(UI.Text("Tick every node the set plays on: its universes go to them in this order.", Font.Callout).Secondary().Wrap());
        foreach (var n in w.Nodes)
        {
            var on = w.ChosenNodes.Contains(n);
            var outputs = n.Outputs is { } o ? $" · {o} output{(o == 1 ? "" : "s")}" : "";
            s.Children.Add(ChoiceCard.Build(UI.HStack(10,
                UI.Icon(on ? "checkmark.circle.fill" : "circle")
                    .Foreground(on ? Tint.Brush(Tint.Accent) : Theme.Brush("TextFillColorSecondaryBrush")),
                UI.VStack(1, UI.Text(n.Name.Length == 0 ? n.Ip : n.Name),
                          UI.Text(n.Ip + outputs + (n.LongName is { } l ? $" · {l}" : ""), Font.Caption).Secondary()).Grow()),
                () => w.ChosenNodes = on ? [.. w.ChosenNodes.Where(x => x != n)]
                                         : [.. w.Nodes.Where(x => w.ChosenNodes.Contains(x) || x == n)]));
        }
        s.Children.Add(LaterHint());
        return s;
    }

    static UIElement LaterHint() =>
        Form.Note("plus.circle", "More controllers later, or a node together with a USB interface: the DMX Output page in the sidebar (Ctrl+Shift+D).");

    UIElement UsbList()
    {
        var s = UI.VStack(8,
            UI.HStack(8,
                UI.Button(w.SearchingUSB ? "Looking…" : "Find USB Interfaces", () => _ = w.FindUSB(model.Api)).Disabled(w.SearchingUSB),
                w.SearchingUSB ? UI.Spinner() : null),
            UI.Text("ENTTEC DMX USB Pro / Pro Mk2, DMXking ultraDMX, Eurolite USB-DMX512-PRO and other Pro-compatible interfaces. One universe per interface.",
                    Font.Callout).Secondary().Wrap());
        if (w.Usb.Count == 0 && !w.SearchingUSB)
            s.Children.Add(Form.Note("cable.connector.slash",
                "Nothing found. Plug it in, or keep “first one found”: the engine looks again when the show starts."));
        foreach (var u in w.Usb)
        {
            var title = u.IsPro ? "DMX USB Pro" + (u.WidgetSerial is { } serial ? $" #{serial}" : "") : u.Description ?? u.Port;
            var detail = string.Join(" · ", new[] { u.Port, u.Manufacturer, u.Firmware is { } f ? $"firmware {f}" : null }.OfType<string>());
            s.Children.Add(ChoiceCard.Build(UI.HStack(10,
                ChoiceCard.Radio(w.UsbPort == u.Port),
                UI.VStack(1, UI.Text(title), UI.Text(detail, Font.Caption).Secondary()).Grow(),
                u.IsPro ? UI.Icon("checkmark.seal.fill").Foreground(Tint.Green) : null),
                () => w.UsbPort = u.Port));
        }
        return s;
    }
}
