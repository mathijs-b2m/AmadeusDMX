// Win32 for the LED Wall Output (what NSScreen, CGDisplay and NSWindow do for the Mac's WallOutputController): the
// monitors connected now with their pixels, refresh and a stable id, and plain windows to draw the output into.
//
// Monitors: EnumDisplayMonitors + GetMonitorInfo (where each is, its GDI name \\.\DISPLAYn), EnumDisplaySettings
// (the mode it runs: the pixels it sends, the refresh), and the display configuration (QueryDisplayConfig +
// DisplayConfigGetDeviceInfo) for the monitor's own name ("DELL U2720Q", or the LED processor's EDID name), its
// device path (the same across restarts and plugging in again on the same port: the id the settings keep) and its
// preferred (native) mode. The process is per-monitor DPI aware (app.manifest: PerMonitorV2), so every rectangle here
// is in physical pixels, whatever the scaling in Settings › Display.
using System.Runtime.InteropServices;

namespace AmadeusDMX;

/// A monitor connected now: where it is on the desktop, the pixels its mode sends (the same size unless it is turned),
/// its refresh (0: unknown) and its preferred mode (nil: unknown).
internal sealed record MonitorInfo(IntPtr Handle, string GdiName, string Id, string Name, WallOutputNative.RECT Bounds, int PixelW, int PixelH,
                                   double Refresh, (int W, int H)? Native);

internal static partial class WallOutputNative
{
    // MARK: monitors

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT
    {
        public int Left, Top, Right, Bottom;
        public readonly int Width => Right - Left;
        public readonly int Height => Bottom - Top;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct MONITORINFOEX
    {
        public int cbSize;
        public RECT rcMonitor, rcWork;
        public uint dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szDevice;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct DISPLAY_DEVICE
    {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public uint StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }

    delegate bool MonitorEnumProc(IntPtr monitor, IntPtr hdc, IntPtr rect, IntPtr data);

    [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc proc, IntPtr data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool GetMonitorInfoW(IntPtr monitor, ref MONITORINFOEX info);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumDisplaySettingsW(string device, int mode, [In, Out] byte[] devMode);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumDisplayDevicesW(string? device, uint index, ref DISPLAY_DEVICE dd, uint flags);
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr hwnd, uint flags);
    [DllImport("user32.dll")] static extern int GetDisplayConfigBufferSizes(uint flags, out uint paths, out uint modes);
    [DllImport("user32.dll")] static extern int QueryDisplayConfig(uint flags, ref uint paths, IntPtr pathInfo, ref uint modes, IntPtr modeInfo, IntPtr topology);
    [DllImport("user32.dll")] static extern int DisplayConfigGetDeviceInfo(IntPtr packet);

    public const uint MONITOR_DEFAULTTONEAREST = 2;

    /// The monitors connected now, in Windows's order.
    public static List<MonitorInfo> Monitors()
    {
        var config = DisplayConfig();
        var list = new List<MonitorInfo>();
        EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, (h, _, _, _) =>
        {
            var mi = new MONITORINFOEX { cbSize = Marshal.SizeOf<MONITORINFOEX>(), szDevice = "" };
            if (!GetMonitorInfoW(h, ref mi)) return true;
            var gdi = mi.szDevice;
            int w = mi.rcMonitor.Right - mi.rcMonitor.Left, ht = mi.rcMonitor.Bottom - mi.rcMonitor.Top;
            double refresh = 0;
            var dm = new byte[220];   // DEVMODEW
            BitConverter.TryWriteBytes(dm.AsSpan(68, 2), (ushort)220);   // dmSize
            if (EnumDisplaySettingsW(gdi, -1 /* ENUM_CURRENT_SETTINGS */, dm))
            {
                // the mode's own pixels (what goes down the cable); the monitor's rectangle is the same with
                // per-monitor DPI awareness, unless the desktop is rotated
                int pw = BitConverter.ToInt32(dm, 172), ph = BitConverter.ToInt32(dm, 176);
                if (pw > 0 && ph > 0) (w, ht) = (pw, ph);
                refresh = BitConverter.ToInt32(dm, 184);
                if (refresh <= 1) refresh = 0;   // 0 or 1: the hardware's default
            }
            config.TryGetValue(gdi, out var c);
            string? id = c.Path, name = c.Name;
            if (string.IsNullOrEmpty(id) || string.IsNullOrEmpty(name))
            {
                var dd = new DISPLAY_DEVICE { cb = Marshal.SizeOf<DISPLAY_DEVICE>() };
                if (EnumDisplayDevicesW(gdi, 0, ref dd, 1 /* EDD_GET_DEVICE_INTERFACE_NAME */))
                {
                    if (string.IsNullOrEmpty(id)) id = dd.DeviceID;
                    if (string.IsNullOrEmpty(name)) name = dd.DeviceString;
                }
            }
            if (string.IsNullOrEmpty(id)) id = gdi;
            if (string.IsNullOrEmpty(name) || name == "Generic PnP Monitor")
                name = gdi.Replace(@"\\.\DISPLAY", "Display ", StringComparison.OrdinalIgnoreCase);
            list.Add(new MonitorInfo(h, gdi, id!, name!, mi.rcMonitor, w, ht, refresh, c.Native));
            return true;
        }, IntPtr.Zero);
        return list;
    }

    /// Per GDI name (\\.\DISPLAY2): the monitor's device path, its own name and its preferred mode, from the
    /// display configuration (empty when it can't be read: then EnumDisplayDevices stands in).
    static Dictionary<string, (string? Path, string? Name, (int W, int H)? Native)> DisplayConfig()
    {
        var result = new Dictionary<string, (string?, string?, (int, int)?)>(StringComparer.OrdinalIgnoreCase);
        const uint QDC_ONLY_ACTIVE_PATHS = 2;
        const int PathSize = 72, ModeSize = 64;
        if (GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, out var nPaths, out var nModes) != 0) return result;
        var paths = Marshal.AllocHGlobal((int)(nPaths * PathSize));
        var modes = Marshal.AllocHGlobal((int)(nModes * ModeSize));
        var packet = Marshal.AllocHGlobal(512);
        try
        {
            if (QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ref nPaths, paths, ref nModes, modes, IntPtr.Zero) != 0) return result;
            for (var i = 0; i < nPaths; i++)
            {
                var p = paths + i * PathSize;
                // the source (the GDI device) and the target (the monitor): adapter LUID and id each
                long srcAdapter = Marshal.ReadInt64(p, 0), tgtAdapter = Marshal.ReadInt64(p, 20);
                int srcId = Marshal.ReadInt32(p, 8), tgtId = Marshal.ReadInt32(p, 28);
                if (Info(packet, 1 /* GET_SOURCE_NAME */, 84, srcAdapter, srcId) is not true) continue;
                var gdi = Marshal.PtrToStringUni(packet + 20, 32).TrimEnd('\0');
                if (result.ContainsKey(gdi)) continue;   // a mirrored monitor: the first one names it
                string? name = null, path = null;
                if (Info(packet, 2 /* GET_TARGET_NAME */, 420, tgtAdapter, tgtId) is true)
                {
                    name = Marshal.PtrToStringUni(packet + 36, 64).TrimEnd('\0');
                    path = Marshal.PtrToStringUni(packet + 164, 128).TrimEnd('\0');
                }
                (int, int)? native = null;
                if (Info(packet, 3 /* GET_TARGET_PREFERRED_MODE */, 80, tgtAdapter, tgtId) is true)
                {
                    int w = Marshal.ReadInt32(packet, 20), h = Marshal.ReadInt32(packet, 24);
                    if (w > 0 && h > 0) native = (w, h);
                }
                result[gdi] = (path, name, native);
            }
        }
        catch (Exception e) when (e is EntryPointNotFoundException or DllNotFoundException) { }
        finally
        {
            Marshal.FreeHGlobal(paths);
            Marshal.FreeHGlobal(modes);
            Marshal.FreeHGlobal(packet);
        }
        return result;
    }

    /// DisplayConfigGetDeviceInfo into `packet`: its header (type, size, adapter, id), then the answer.
    static bool Info(IntPtr packet, int type, int size, long adapter, int id)
    {
        for (var k = 0; k < size; k += 4) Marshal.WriteInt32(packet, k, 0);
        Marshal.WriteInt32(packet, 0, type);
        Marshal.WriteInt32(packet, 4, size);
        Marshal.WriteInt64(packet, 8, adapter);
        Marshal.WriteInt32(packet, 16, id);
        return DisplayConfigGetDeviceInfo(packet) == 0;
    }

    // MARK: windows

    public delegate IntPtr WndProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WNDCLASSEX
    {
        public int cbSize;
        public uint style;
        public IntPtr lpfnWndProc;
        public int cbClsExtra, cbWndExtra;
        public IntPtr hInstance, hIcon, hCursor, hbrBackground;
        public string? lpszMenuName;
        public string lpszClassName;
        public IntPtr hIconSm;
    }

    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern ushort RegisterClassExW(ref WNDCLASSEX wc);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateWindowExW(uint exStyle, string className, string title, uint style, int x, int y, int w, int h,
                                         IntPtr parent, IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] public static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern IntPtr DefWindowProcW(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hwnd, IntPtr after, int x, int y, int w, int h, uint flags);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hwnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out RECT r);
    [DllImport("user32.dll")] public static extern bool AdjustWindowRectExForDpi(ref RECT r, uint style, bool menu, uint exStyle, uint dpi);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr LoadCursorW(IntPtr instance, IntPtr name);
    [DllImport("gdi32.dll")] static extern IntPtr GetStockObject(int obj);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandleW(string? name);
    [DllImport("kernel32.dll")] public static extern uint WaitForSingleObjectEx(IntPtr handle, uint ms, bool alertable);
    [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);

    public const uint WS_POPUP = 0x80000000, WS_VISIBLE = 0x10000000, WS_OVERLAPPEDWINDOW = 0x00CF0000;
    public const uint WS_EX_TOPMOST = 0x8, WS_EX_TOOLWINDOW = 0x80, WS_EX_NOACTIVATE = 0x08000000, WS_EX_APPWINDOW = 0x40000;
    public const uint WM_DESTROY = 0x2, WM_SIZE = 0x5, WM_CLOSE = 0x10, WM_ERASEBKGND = 0x14, WM_DISPLAYCHANGE = 0x7E,
                      WM_MOUSEACTIVATE = 0x21, WM_SIZING = 0x214, WM_DPICHANGED = 0x2E0, WM_SETTINGCHANGE = 0x1A;
    public const int MA_NOACTIVATE = 3, SW_HIDE = 0, SW_SHOWNOACTIVATE = 4, SW_SHOW = 5;
    public static readonly IntPtr HWND_TOPMOST = new(-1);
    public const uint SWP_NOACTIVATE = 0x10, SWP_NOZORDER = 0x4, SWP_SHOWWINDOW = 0x40, SWP_FRAMECHANGED = 0x20;
    public const uint ES_CONTINUOUS = 0x80000000, ES_DISPLAY_REQUIRED = 0x2;

    static readonly HashSet<string> Classes = [];
    static readonly Dictionary<IntPtr, WndProc> Handlers = [];
    static readonly WndProc Dispatcher = Dispatch;   // kept alive: Windows calls it for as long as the app runs
    const uint WM_NCDESTROY = 0x82;

    static IntPtr Dispatch(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (!Handlers.TryGetValue(hwnd, out var handler)) return DefWindowProcW(hwnd, msg, wParam, lParam);
        if (msg == WM_NCDESTROY) Handlers.Remove(hwnd);
        return handler(hwnd, msg, wParam, lParam);
    }

    /// A window of `className` (registered on first use: a black background, an arrow cursor) on the calling thread
    /// (the UI thread: its message loop runs it); `handler` gets its messages (DefWindowProcW for the rest).
    public static IntPtr CreateWindow(string className, WndProc handler, string title, uint style, uint exStyle, int x, int y, int w, int h)
    {
        var instance = GetModuleHandleW(null);
        if (Classes.Add(className))
        {
            var wc = new WNDCLASSEX
            {
                cbSize = Marshal.SizeOf<WNDCLASSEX>(), lpfnWndProc = Marshal.GetFunctionPointerForDelegate(Dispatcher), hInstance = instance,
                hCursor = LoadCursorW(IntPtr.Zero, 32512 /* IDC_ARROW */), hbrBackground = GetStockObject(4 /* BLACK_BRUSH */),
                lpszClassName = className,
            };
            RegisterClassExW(ref wc);
        }
        var hwnd = CreateWindowExW(exStyle, className, title, style & ~WS_VISIBLE, x, y, w, h, IntPtr.Zero, IntPtr.Zero, instance, IntPtr.Zero);
        if (hwnd != IntPtr.Zero) Handlers[hwnd] = handler;
        return hwnd;
    }
}
