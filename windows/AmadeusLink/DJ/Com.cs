// A little COM and WinRT by hand, for the few interfaces Amadeus Link calls (UI Automation for djay, the shell's
// track length, Windows MIDI Services' loopback): each call names its interface and its slot in the interface's
// method table, as the system's headers and metadata list them (IUnknown's three methods come first, IInspectable
// adds three more). No generated interop, no type libraries: what is called is exactly what is written here.
using System.Runtime.InteropServices;

namespace AmadeusLink;

static unsafe partial class Com
{
    /// The function in `slot` of the interface `p` points to.
    public static void* Slot(IntPtr p, int slot) => (*(void***)p)[slot];

    public static void Check(int hr)
    {
        if (hr < 0) Marshal.ThrowExceptionForHR(hr);
    }

    public static void Release(IntPtr p)
    {
        if (p != IntPtr.Zero) Marshal.Release(p);
    }

    /// A BSTR the callee gave us, as a string (and freed).
    public static string? Bstr(IntPtr b)
    {
        if (b == IntPtr.Zero) return null;
        try { return Marshal.PtrToStringBSTR(b); }
        finally { Marshal.FreeBSTR(b); }
    }

    /// COM for this thread: the multithreaded apartment (UI Automation and WinRT objects shared by Link's threads).
    public static void Attach() => CoInitializeEx(IntPtr.Zero, 0 /* COINIT_MULTITHREADED */);

    public static IntPtr Create(Guid clsid, Guid iid)
    {
        Check(CoCreateInstance(clsid, IntPtr.Zero, 1 /* CLSCTX_INPROC_SERVER */, iid, out var p));
        return p;
    }

    // MARK: WinRT

    /// A WinRT class's factory or statics, as the interface `iid`.
    public static IntPtr Factory(string runtimeClass, Guid iid)
    {
        using var name = new HString(runtimeClass);
        Check(RoGetActivationFactory(name.Handle, iid, out var f));
        return f;
    }

    /// An HSTRING for a call (freed after it).
    public sealed class HString : IDisposable
    {
        public IntPtr Handle { get; }
        public HString(string s)
        {
            Check(WindowsCreateString(s, (uint)s.Length, out var h));
            Handle = h;
        }
        public void Dispose() => WindowsDeleteString(Handle);
    }

    /// An HSTRING the callee gave us, as a string (and freed).
    public static string HStringValue(IntPtr h)
    {
        if (h == IntPtr.Zero) return "";
        try
        {
            var raw = WindowsGetStringRawBuffer(h, out var length);
            return new string((char*)raw, 0, (int)length);
        }
        finally { WindowsDeleteString(h); }
    }

    [LibraryImport("ole32.dll")] private static partial int CoInitializeEx(IntPtr reserved, uint coinit);
    [LibraryImport("ole32.dll")] private static partial int CoCreateInstance(in Guid clsid, IntPtr outer, uint context, in Guid iid, out IntPtr p);
    [LibraryImport("combase.dll")] private static partial int RoGetActivationFactory(IntPtr classId, in Guid iid, out IntPtr factory);
    [LibraryImport("combase.dll", StringMarshalling = StringMarshalling.Utf16)] private static partial int WindowsCreateString(string s, uint length, out IntPtr h);
    [LibraryImport("combase.dll")] private static partial int WindowsDeleteString(IntPtr h);
    [LibraryImport("combase.dll")] private static partial IntPtr WindowsGetStringRawBuffer(IntPtr h, out uint length);
}

/// A COM interface pointer that is released when it is no longer used (by the finalizer: a reader thread may still
/// hold a control another thread has replaced).
sealed class ComRef(IntPtr p, string label = "")
{
    public IntPtr P { get; } = p;
    /// What it is called (a UI Automation control's name).
    public string Label { get; } = label;
    ~ComRef() => Com.Release(P);
}
