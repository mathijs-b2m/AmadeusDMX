// The MIDI ports Windows has (WinMM, as Mixxx and the engine see them): for Settings › Integrations › Mixxx.
using System.Runtime.InteropServices;

namespace AmadeusDMX;

public static class MidiPorts
{
    /// The MIDI input ports' names (the engine opens the "Amadeus DMX" input; Mixxx pairs it with the output).
    public static IReadOnlyList<string> Inputs()
    {
        if (!OperatingSystem.IsWindows()) return [];
        var names = new List<string>();
        try
        {
            var n = midiInGetNumDevs();
            for (uint i = 0; i < n; i++)
                if (midiInGetDevCapsW((nuint)i, out var caps, (uint)Marshal.SizeOf<MIDIINCAPSW>()) == 0) names.Add(caps.szPname);
        }
        catch (Exception e) when (e is DllNotFoundException or EntryPointNotFoundException) { }
        return names;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct MIDIINCAPSW
    {
        public ushort wMid;
        public ushort wPid;
        public uint vDriverVersion;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szPname;
        public uint dwSupport;
    }

    [DllImport("winmm.dll")]
    static extern uint midiInGetNumDevs();

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    static extern uint midiInGetDevCapsW(nuint uDeviceID, out MIDIINCAPSW caps, uint cbMidiInCaps);
}
