// The notification-area icon (the Mac's menu bar extra): Shell_NotifyIcon on a hidden message window of the UI
// thread. A click shows Link's window; a right-click opens a small menu. Comes back by itself when Explorer
// restarts (TaskbarCreated).
using System.Runtime.InteropServices;

namespace AmadeusLink;

public sealed partial class TrayIcon : IDisposable
{
    /// One line of the menu (a nil action: a line of text; Separator: a divider).
    public sealed record Entry(string Title, Action? Action, bool Checked = false)
    {
        public static readonly Entry Separator = new("-", null);
    }

    const int WM_APP = 0x8000, WM_TRAY = WM_APP + 1, WM_LBUTTONUP = 0x0202, WM_RBUTTONUP = 0x0205, WM_CONTEXTMENU = 0x007B,
              WM_NULL = 0, NIN_SELECT = 0x0400, NIN_KEYSELECT = 0x0401;
    const uint NIM_ADD = 0, NIM_MODIFY = 1, NIM_DELETE = 2, NIM_SETVERSION = 4, NIF_MESSAGE = 1, NIF_ICON = 2, NIF_TIP = 4,
               NIF_SHOWTIP = 0x80, NOTIFYICON_VERSION_4 = 4;
    const uint MF_STRING = 0, MF_GRAYED = 1, MF_CHECKED = 8, MF_SEPARATOR = 0x800, TPM_RETURNCMD = 0x100, TPM_RIGHTBUTTON = 2;

    readonly WndProc _proc;   // kept: Windows calls it for as long as the window lives
    readonly IntPtr _hwnd, _icon;
    readonly uint _taskbarCreated;
    readonly Action _click;
    readonly Func<IReadOnlyList<Entry>> _menu;
    string _tooltip;

    public TrayIcon(string iconPath, string tooltip, Action click, Func<IReadOnlyList<Entry>> menu)
    {
        _tooltip = tooltip;
        _click = click;
        _menu = menu;
        _icon = LoadImage(IntPtr.Zero, iconPath, 1 /* IMAGE_ICON */, GetSystemMetrics(49), GetSystemMetrics(50), 0x10 /* LR_LOADFROMFILE */);
        _proc = Proc;
        var cls = new WNDCLASSEX
        {
            cbSize = (uint)Marshal.SizeOf<WNDCLASSEX>(),
            lpfnWndProc = Marshal.GetFunctionPointerForDelegate(_proc),
            hInstance = GetModuleHandle(null),
            lpszClassName = "AmadeusLinkTray",
        };
        RegisterClassEx(ref cls);
        _hwnd = CreateWindowEx(0, cls.lpszClassName, "", 0, 0, 0, 0, 0, new IntPtr(-3) /* HWND_MESSAGE */, IntPtr.Zero, cls.hInstance, IntPtr.Zero);
        _taskbarCreated = RegisterWindowMessage("TaskbarCreated");
        Add();
    }

    /// What the icon says when the pointer rests on it.
    public string Tooltip
    {
        get => _tooltip;
        set
        {
            if (value == _tooltip) return;
            _tooltip = value;
            var d = Data(NIF_TIP | NIF_SHOWTIP);
            Shell_NotifyIcon(NIM_MODIFY, ref d);
        }
    }

    NOTIFYICONDATA Data(uint flags) => new()
    {
        cbSize = (uint)Marshal.SizeOf<NOTIFYICONDATA>(),
        hWnd = _hwnd,
        uID = 1,
        uFlags = flags,
        uCallbackMessage = WM_TRAY,
        hIcon = _icon,
        szTip = _tooltip.Length > 127 ? _tooltip[..127] : _tooltip,
        uTimeoutOrVersion = NOTIFYICON_VERSION_4,
    };

    void Add()
    {
        var d = Data(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP);
        Shell_NotifyIcon(NIM_ADD, ref d);
        Shell_NotifyIcon(NIM_SETVERSION, ref d);
    }

    IntPtr Proc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (msg == WM_TRAY)
        {
            switch ((int)(lParam.ToInt64() & 0xFFFF))  // NOTIFYICON_VERSION_4: the event in the low word
            {
                case WM_LBUTTONUP or NIN_SELECT or NIN_KEYSELECT: _click(); break;
                case WM_CONTEXTMENU or WM_RBUTTONUP: ShowMenu(); break;
            }
            return IntPtr.Zero;
        }
        if (msg == _taskbarCreated) Add();  // Explorer restarted: the icon is gone, put it back
        return DefWindowProc(hwnd, msg, wParam, lParam);
    }

    void ShowMenu()
    {
        var entries = _menu();
        var menu = CreatePopupMenu();
        for (var i = 0; i < entries.Count; i++)
        {
            var e = entries[i];
            if (ReferenceEquals(e, Entry.Separator)) { AppendMenu(menu, MF_SEPARATOR, UIntPtr.Zero, null); continue; }
            var flags = MF_STRING | (e.Checked ? MF_CHECKED : 0) | (e.Action is null ? MF_GRAYED : 0);
            AppendMenu(menu, flags, (UIntPtr)(i + 1), e.Title);
        }
        GetCursorPos(out var pt);
        SetForegroundWindow(_hwnd);  // else the menu doesn't close when you click elsewhere
        var chosen = TrackPopupMenuEx(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.X, pt.Y, _hwnd, IntPtr.Zero);
        PostMessage(_hwnd, WM_NULL, IntPtr.Zero, IntPtr.Zero);
        DestroyMenu(menu);
        if (chosen > 0 && chosen <= entries.Count) entries[chosen - 1].Action?.Invoke();
    }

    public void Dispose()
    {
        var d = Data(0);
        Shell_NotifyIcon(NIM_DELETE, ref d);
        DestroyWindow(_hwnd);
        if (_icon != IntPtr.Zero) DestroyIcon(_icon);
    }

    // MARK: Win32

    delegate IntPtr WndProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WNDCLASSEX
    {
        public uint cbSize, style;
        public IntPtr lpfnWndProc;
        public int cbClsExtra, cbWndExtra;
        public IntPtr hInstance, hIcon, hCursor, hbrBackground;
        public string? lpszMenuName;
        public string lpszClassName;
        public IntPtr hIconSm;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct NOTIFYICONDATA
    {
        public uint cbSize;
        public IntPtr hWnd;
        public uint uID, uFlags, uCallbackMessage;
        public IntPtr hIcon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string szTip;
        public uint dwState, dwStateMask;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string szInfo;
        public uint uTimeoutOrVersion;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string szInfoTitle;
        public uint dwInfoFlags;
        public Guid guidItem;
        public IntPtr hBalloonIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct POINT { public int X, Y; }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] static extern bool Shell_NotifyIcon(uint message, ref NOTIFYICONDATA data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern ushort RegisterClassEx(ref WNDCLASSEX cls);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr CreateWindowEx(uint exStyle, string cls, string name, uint style, int x, int y, int w, int h, IntPtr parent,
                                        IntPtr menu, IntPtr instance, IntPtr param);
    [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern IntPtr DefWindowProc(IntPtr hwnd, uint msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern uint RegisterWindowMessage(string name);
    [DllImport("user32.dll")] static extern IntPtr CreatePopupMenu();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool AppendMenu(IntPtr menu, uint flags, UIntPtr id, string? text);
    [DllImport("user32.dll")] static extern int TrackPopupMenuEx(IntPtr menu, uint flags, int x, int y, IntPtr hwnd, IntPtr tpm);
    [DllImport("user32.dll")] static extern bool DestroyMenu(IntPtr menu);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT pt);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern IntPtr LoadImage(IntPtr instance, string name, uint type, int cx, int cy, uint load);
    [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr icon);
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)] static extern IntPtr GetModuleHandle(string? name);
}
