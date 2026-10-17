// MIDI in through WinMM: what the Mixxx reader needs, SysEx included (a port of amadeus/show/sources/winmidi.py).
// WinMM sees every MIDI 1.0 port: a Windows MIDI Services loopback as well as a loopMIDI port, and both let Mixxx
// and Amadeus Link open the same port at once.
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;

namespace AmadeusLink;

sealed unsafe partial class WinMidiIn : IDisposable
{
    const uint CALLBACK_FUNCTION = 0x00030000, MIM_LONGDATA = 0x3C4;
    const int Buffers = 8, BufferSize = 1024;  // SysEx buffers WinMM fills; a longer message continues in the next one

    [StructLayout(LayoutKind.Sequential)]
    struct MIDIHDR
    {
        public IntPtr lpData;
        public uint dwBufferLength, dwBytesRecorded;
        public IntPtr dwUser;
        public uint dwFlags;
        public IntPtr lpNext, reserved;
        public uint dwOffset;
        public fixed long dwReserved[8];
    }

    [StructLayout(LayoutKind.Sequential)]
    struct MIDIINCAPSW
    {
        public ushort wMid, wPid;
        public uint vDriverVersion;
        public fixed char szPname[32];
        public uint dwSupport;
    }

    /// The MIDI inputs WinMM sees, in its order.
    public static List<string> InputNames()
    {
        List<string> names = [];
        var n = midiInGetNumDevs();
        for (uint i = 0; i < n; i++)
        {
            MIDIINCAPSW caps;
            names.Add(midiInGetDevCapsW(i, &caps, (uint)sizeof(MIDIINCAPSW)) == 0 ? new string(caps.szPname) : "");
        }
        return names;
    }

    readonly IntPtr _handle;
    readonly MIDIHDR*[] _headers = new MIDIHDR*[Buffers];
    readonly Action<byte[]> _message;
    readonly SysExAssembler _sysex = new();
    readonly Lock _lock = new();
    GCHandle _self;
    volatile bool _closing;

    /// Opens WinMM's input `index` and hands every SysEx message to `message` (other messages are ignored).
    public WinMidiIn(uint index, Action<byte[]> message)
    {
        _message = message;
        _self = GCHandle.Alloc(this);
        IntPtr h;
        var err = midiInOpen(&h, index, (IntPtr)(delegate* unmanaged[Stdcall]<IntPtr, uint, IntPtr, IntPtr, IntPtr, void>)&Event,
                             GCHandle.ToIntPtr(_self), CALLBACK_FUNCTION);
        if (err != 0)
        {
            _self.Free();
            throw new MidiPortException($"The MIDI port can't be opened (WinMM error {err}): is a program that doesn't share it using it?");
        }
        _handle = h;
        for (var i = 0; i < Buffers; i++)
        {
            var hdr = (MIDIHDR*)NativeMemory.AllocZeroed((nuint)sizeof(MIDIHDR));
            hdr->lpData = (IntPtr)NativeMemory.AllocZeroed(BufferSize);
            hdr->dwBufferLength = BufferSize;
            _headers[i] = hdr;
            midiInPrepareHeader(_handle, hdr, (uint)sizeof(MIDIHDR));
            midiInAddBuffer(_handle, hdr, (uint)sizeof(MIDIHDR));
        }
        midiInStart(_handle);
    }

    [UnmanagedCallersOnly(CallConvs = [typeof(CallConvStdcall)])]
    static void Event(IntPtr handle, uint msg, IntPtr instance, IntPtr param1, IntPtr param2)
    {
        if (msg != MIM_LONGDATA || instance == IntPtr.Zero) return;
        try
        {
            if (GCHandle.FromIntPtr(instance).Target is WinMidiIn self) self.Long((MIDIHDR*)param1);
        }
        catch (Exception) { }  // never let an exception unwind into WinMM
    }

    void Long(MIDIHDR* hdr)
    {
        if (_closing) return;  // midiInReset hands the buffers back empty: keep them
        var data = new ReadOnlySpan<byte>((void*)hdr->lpData, (int)hdr->dwBytesRecorded).ToArray();
        // back to WinMM at once (as RtMidi does, from this callback): the next message needs a buffer
        midiInAddBuffer(_handle, hdr, (uint)sizeof(MIDIHDR));
        List<byte[]> messages;
        lock (_lock) messages = _sysex.Feed(data);
        foreach (var m in messages) _message(m);
    }

    public void Dispose()
    {
        if (_closing) return;
        _closing = true;
        midiInStop(_handle);
        midiInReset(_handle);  // hands the buffers back
        foreach (var hdr in _headers)
        {
            midiInUnprepareHeader(_handle, hdr, (uint)sizeof(MIDIHDR));
            NativeMemory.Free((void*)hdr->lpData);
            NativeMemory.Free(hdr);
        }
        midiInClose(_handle);
        _self.Free();
    }

    [LibraryImport("winmm.dll")] private static partial uint midiInGetNumDevs();
    [LibraryImport("winmm.dll")] private static partial uint midiInGetDevCapsW(nuint id, MIDIINCAPSW* caps, uint size);
    [LibraryImport("winmm.dll")] private static partial uint midiInOpen(IntPtr* handle, uint id, IntPtr callback, IntPtr instance, uint flags);
    [LibraryImport("winmm.dll")] private static partial uint midiInPrepareHeader(IntPtr h, MIDIHDR* hdr, uint size);
    [LibraryImport("winmm.dll")] private static partial uint midiInUnprepareHeader(IntPtr h, MIDIHDR* hdr, uint size);
    [LibraryImport("winmm.dll")] private static partial uint midiInAddBuffer(IntPtr h, MIDIHDR* hdr, uint size);
    [LibraryImport("winmm.dll")] private static partial uint midiInStart(IntPtr h);
    [LibraryImport("winmm.dll")] private static partial uint midiInStop(IntPtr h);
    [LibraryImport("winmm.dll")] private static partial uint midiInReset(IntPtr h);
    [LibraryImport("winmm.dll")] private static partial uint midiInClose(IntPtr h);
}
