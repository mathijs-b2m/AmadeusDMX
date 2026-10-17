// Windows MIDI Services (the new MIDI stack of Windows 11): a "basic loopback" endpoint called "Amadeus DMX",
// which programs using WinMM (Mixxx, through PortMidi, and Amadeus Link's own WinMidiIn) see as one MIDI 1.0 input
// and one output of that name; what Mixxx sends to the output comes back on the input. The Mac's CoreMIDI virtual
// device, as near as Windows has one. Findings and what it needs: windows/README.md, "Amadeus Link and Mixxx".
//
// Called through WinRT's ABI by hand (Com.cs): the API (Windows.Devices.Midi2, metadata locked in In-box Preview
// 11, October 2026) has no .NET projection on NuGet; the interface ids and slots below are from its
// Windows.Devices.Midi2.winmd. Where it isn't there (older Windows, the basic loopback transport not installed,
// the service off) nothing happens and Link looks for a port someone made (loopMIDI).
//
// The loopback is "transient": it lives until Windows restarts (or the MIDI service does), not just while Link
// runs, so Mixxx keeps its port when Link is restarted. Link makes it again only when it's gone.
namespace AmadeusLink;

static unsafe class MidiServices
{
    const string Ns = "Windows.Devices.Midi2";
    const string UniqueId = "amadeusdmx";

    static readonly Guid IMidiApiStatics = new("8087b303-0519-c0de-31d1-ee0010000000");
    static readonly Guid IManagerStatics = new("8087b303-0519-c0de-31d1-ee00f0101000");
    static readonly Guid IDefinitionFactory = new("8087b303-0519-c0de-31d1-ff00f0108000");
    static readonly Guid ICreationConfigFactory = new("8087b303-0519-c0de-31d1-ff00f0102000");

    /// Makes the loopback `name` unless it's there. nil when there is one now; else why there isn't.
    public static string? EnsureLoopback(string name, string description)
    {
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000)) return "Windows MIDI Services needs Windows 11";
        IntPtr api = IntPtr.Zero, manager = IntPtr.Zero, defs = IntPtr.Zero, configs = IntPtr.Zero, def = IntPtr.Zero, config = IntPtr.Zero,
               response = IntPtr.Zero;
        try
        {
            Com.Attach();
            api = Com.Factory($"{Ns}.MidiApi", IMidiApiStatics);
            byte ok;
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, byte*, int>)Com.Slot(api, 6 /* EnsureServiceAvailable */))(api, &ok));
            if (ok == 0) return "the Windows MIDI Service isn't running";

            const string loopback = $"{Ns}.Transports.BasicLoopback";
            manager = Com.Factory($"{loopback}.MidiBasicLoopbackManager", IManagerStatics);
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, byte*, int>)Com.Slot(manager, 6 /* get_IsTransportAvailable */))(manager, &ok));
            if (ok == 0) return "its basic loopback transport isn't installed";
            using (var id = new Com.HString(UniqueId))
                Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr, byte*, int>)Com.Slot(manager, 11 /* DoesLoopbackExist */))(manager, id.Handle, &ok));
            if (ok != 0) return null;  // made before (by an earlier Link), still there

            defs = Com.Factory($"{loopback}.MidiBasicLoopbackEndpointDefinition", IDefinitionFactory);
            using (var n = new Com.HString(name))
            using (var d = new Com.HString(description))
            using (var id = new Com.HString(UniqueId))
                Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr, IntPtr, IntPtr, IntPtr*, int>)Com.Slot(defs, 8 /* CreateInstance3 */))(
                    defs, n.Handle, d.Handle, id.Handle, &def));
            configs = Com.Factory($"{loopback}.MidiBasicLoopbackCreationConfig", ICreationConfigFactory);
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr, IntPtr*, int>)Com.Slot(configs, 6 /* CreateInstance */))(configs, def, &config));
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr, IntPtr*, int>)Com.Slot(manager, 8 /* CreateTransientLoopback */))(manager, config, &response));
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, byte*, int>)Com.Slot(response, 6 /* get_Success */))(response, &ok));
            if (ok != 0) return null;
            IntPtr message;
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(response, 8 /* get_ErrorMessage */))(response, &message));
            var why = Com.HStringValue(message);
            return why.Length > 0 ? why : "it couldn't make the loopback";
        }
        catch (Exception e)  // HRESULTs become all sorts of exceptions
        {
            return e.HResult == unchecked((int)0x80040154)  // REGDB_E_CLASSNOTREG: no Windows MIDI Services API here
                ? "Windows MIDI Services isn't on this computer" : $"Windows MIDI Services: {e.Message}";
        }
        finally
        {
            foreach (var p in new[] { response, config, configs, def, defs, manager, api }) Com.Release(p);
        }
    }
}
