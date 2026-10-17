// The DJ software Amadeus Link reads itself, on Windows: djay Pro through UI Automation (UiaWindow), Mixxx through
// a MIDI port called "Amadeus DMX" (made with Windows MIDI Services when it can, else one made in loopMIDI) read
// with WinMM. What they read and how it becomes the plugin's packets is the kit's (AmadeusKit/DJ, tested on a Mac).
using System.Runtime.InteropServices;

namespace AmadeusLink;

static class Readers
{
    /// Made off the UI thread: finding or making a MIDI port can take a moment.
    public static IDJReader Make(LinkServer.Software s)
    {
        Resolver.LengthOf = ShellLength.Of;
        return s == LinkServer.Software.Djay
            ? new DjayReader<ComRef>(new UiaWindow())
            : new MixxxReader(OpenMixxxPort, MixxxMapping());
    }

    /// Our Mixxx mapping: mixxx\ beside the app (build.ps1 puts it there), else the checkout's (a development build).
    static string? MixxxMapping() =>
        new[] { Path.Combine(AppContext.BaseDirectory, "mixxx"), AppSettings.EngineRoot is { } root ? Path.Combine(root, "mixxx") : null }
            .FirstOrDefault(Directory.Exists);

    public const string LoopMidiUrl = "https://www.tobias-erichsen.de/software/loopmidi.html";

    /// The input of the port Mixxx sends to: a loopback, so what Mixxx sends comes back on it.
    static (IDisposable, string) OpenMixxxPort(Action<byte[]> message)
    {
        const string name = MixxxReader.Name;
        var index = MidiPorts.Matching(WinMidiIn.InputNames(), name);
        string? why = null;
        if (index is null)
        {
            why = MidiServices.EnsureLoopback(name, "Amadeus Link: Mixxx's decks for the lighting computer");
            for (var i = 0; why is null && index is null && i < 30; i++)  // the new port reaches WinMM after a moment
            {
                Thread.Sleep(100);
                index = MidiPorts.Matching(WinMidiIn.InputNames(), name);
            }
        }
        if (index is not { } at)
            throw new MidiPortException(
                $"No MIDI port \"{name}\" on this laptop, and Amadeus Link can't make one ({why ?? "Windows didn't show it"}). " +
                $"Make a port called \"{name}\" in loopMIDI (free), then switch to Mixxx here again and start Mixxx.");
        var names = WinMidiIn.InputNames();
        return (new WinMidiIn((uint)at, message), at < names.Count ? names[at] : name);
    }
}

/// A track's length from Windows' own properties (System.Media.Duration, what File Explorer shows): any format
/// Windows can play, nothing to decode. The Mac reads it with AVAudioFile.
static unsafe partial class ShellLength
{
    static readonly Guid IShellItem2 = new("7e9fb0d3-919f-4307-ab2e-9b1860310c93");

    [StructLayout(LayoutKind.Sequential)]
    struct PropertyKey { public Guid fmtid; public uint pid; }

    static readonly PropertyKey Duration = new() { fmtid = new Guid("64440490-4c8b-11d1-8b70-080036b11a03"), pid = 3 };  // PKEY_Media_Duration

    public static double? Of(string file)
    {
        Com.Attach();
        var iid = IShellItem2;
        if (SHCreateItemFromParsingName(file, IntPtr.Zero, &iid, out var item) < 0 || item == IntPtr.Zero) return null;
        try
        {
            ulong hundredNs;
            var key = Duration;
            var hr = ((delegate* unmanaged[Stdcall]<IntPtr, PropertyKey*, ulong*, int>)Com.Slot(item, 19 /* IShellItem2.GetUInt64 */))(item, &key, &hundredNs);
            return hr >= 0 && hundredNs > 0 ? hundredNs / 1e7 : null;
        }
        finally { Com.Release(item); }
    }

    [LibraryImport("shell32.dll", StringMarshalling = StringMarshalling.Utf16)]
    private static partial int SHCreateItemFromParsingName(string path, IntPtr bindContext, Guid* iid, out IntPtr item);
}
