// djay Pro for Windows' window, read through UI Automation the way Narrator reads it (the Windows side of the
// kit's DjayReader; amadeus/show/sources/djay.py UiaWindow does the same for the engine).
//
// What Amadeus Link does here, and nothing else (docs/dj-software.md, "djay Pro for Windows and UI Automation"):
//   1. find djay's top-level window: the windows of a program whose name has "djay" in it (a Store app's frame
//      window: by its title, which starts with "djay"); no other window is opened or read;
//   2. find its deck controls by their Narrator labels ("Elapsed time, Deck 1", …, inside the "Decks" group when
//      there is one), keeping only those labels;
//   3. read their values: the Value pattern's text, else the Toggle state, the RangeValue, the Text pattern's text
//      or the legacy value, in that order.
// Only "get" calls: UI Automation's methods that click, type, focus, select or set values (SetFocus, SetValue,
// Toggle, Select, DoDefaultAction) are never called. No permission is needed: UI Automation reads programs that
// run as the same user (not one running as administrator).
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace AmadeusLink;

sealed unsafe partial class UiaWindow : IDjayWindow<ComRef>
{
    // UIAutomationClient.h
    static readonly Guid CUIAutomation = new("ff48dba4-60ef-4201-aa87-54103eef594e");
    static readonly Guid IUIAutomation = new("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee");
    static readonly Guid IValuePattern = new("a94cd8b1-0844-4cd6-9d2d-640537ab39e9");
    static readonly Guid ITogglePattern = new("94cf8058-9b8d-4ab9-8bfd-4cd0a33c8c70");
    static readonly Guid IRangeValuePattern = new("59213f4f-7346-49e5-b120-80555987a148");
    static readonly Guid ITextPattern = new("32eba289-3583-42c9-9c59-3b6d9a1e9b6a");
    static readonly Guid ILegacyPattern = new("828055ad-355b-4435-86d5-3b51c14a9b1b");
    const int UIA_NamePropertyId = 30005;
    const int UIA_ValuePatternId = 10002, UIA_RangeValuePatternId = 10003, UIA_TextPatternId = 10014, UIA_TogglePatternId = 10015,
              UIA_LegacyIAccessiblePatternId = 10018;
    const int TreeScope_Descendants = 4;

    // IUIAutomation's slots (3 + its method's index)
    const int ElementFromHandle = 6, CreateTrueCondition = 21, CreatePropertyCondition = 23;
    // IUIAutomationElement's
    const int FindFirst = 5, FindAll = 6, GetCurrentPatternAs = 14, CurrentName = 23;
    // IUIAutomationElementArray's
    const int ArrayLength = 3, ArrayElement = 4;

    readonly Lock _lock = new();
    IntPtr _uia, _true, _decks;
    string _note = "";

    public string Note { get { lock (_lock) return _note; } }

    public void Attach()
    {
        Com.Attach();
        lock (_lock)
        {
            if (_uia != IntPtr.Zero) return;
            try
            {
                _uia = Com.Create(CUIAutomation, IUIAutomation);
                IntPtr cond;
                Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(_uia, CreateTrueCondition))(_uia, &cond));
                _true = cond;
                var name = new Variant { vt = 8 /* VT_BSTR */, data = Marshal.StringToBSTR(DjayLabels.Decks) };
                Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, int, Variant, IntPtr*, int>)Com.Slot(_uia, CreatePropertyCondition))(_uia, UIA_NamePropertyId, name, &cond));
                Marshal.FreeBSTR(name.data);
                _decks = cond;
            }
            catch (Exception e) when (e is COMException or InvalidCastException or DllNotFoundException)
            {
                _note = $"UI Automation isn't available on this computer ({e.Message}): djay Pro can't be read.";
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    struct Variant
    {
        public ushort vt, r1, r2, r3;
        public IntPtr data, data2;
    }

    public Dictionary<string, List<ComRef>> Scan()
    {
        Dictionary<string, List<ComRef>> controls = [];
        if (_uia == IntPtr.Zero) return controls;
        var hwnd = DjayWindow();
        if (hwnd == IntPtr.Zero)
        {
            lock (_lock) if (!_note.StartsWith("UI Automation", StringComparison.Ordinal)) _note = "";
            return controls;
        }
        IntPtr win = IntPtr.Zero, group = IntPtr.Zero, all = IntPtr.Zero;
        try
        {
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, IntPtr, IntPtr*, int>)Com.Slot(_uia, ElementFromHandle))(_uia, hwnd, &win));
            ((delegate* unmanaged[Stdcall]<IntPtr, int, IntPtr, IntPtr*, int>)Com.Slot(win, FindFirst))(win, TreeScope_Descendants, _decks, &group);
            var root = group != IntPtr.Zero ? group : win;
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, int, IntPtr, IntPtr*, int>)Com.Slot(root, FindAll))(root, TreeScope_Descendants, _true, &all));
            int n;
            Com.Check(((delegate* unmanaged[Stdcall]<IntPtr, int*, int>)Com.Slot(all, ArrayLength))(all, &n));
            for (var i = 0; i < n; i++)
            {
                IntPtr e;
                if (((delegate* unmanaged[Stdcall]<IntPtr, int, IntPtr*, int>)Com.Slot(all, ArrayElement))(all, i, &e) < 0 || e == IntPtr.Zero) continue;
                var name = Name(e) ?? "";
                if (!DjayLabels.Wanted(name)) { Com.Release(e); continue; }
                if (!controls.TryGetValue(name, out var list)) controls[name] = list = [];
                list.Add(new ComRef(e, name));
            }
        }
        finally
        {
            Com.Release(all);
            Com.Release(group);
            Com.Release(win);
        }
        lock (_lock)
            _note = controls.Count == 0
                ? "djay Pro's window shows no deck controls Amadeus Link knows (djay Pro for Windows 5 and later label them for Narrator)."
                : "";
        return controls;
    }

    static string? Name(IntPtr e)
    {
        IntPtr b;
        return ((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(e, CurrentName))(e, &b) < 0 ? null : Com.Bstr(b);
    }

    /// The control's pattern as its interface, zero when it has none.
    static IntPtr Pattern(IntPtr e, int id, Guid iid)
    {
        IntPtr p;
        return ((delegate* unmanaged[Stdcall]<IntPtr, int, Guid*, IntPtr*, int>)Com.Slot(e, GetCurrentPatternAs))(e, id, &iid, &p) < 0 ? IntPtr.Zero : p;
    }

    public string? Read(ComRef control)
    {
        var e = control.P;
        string? value = null;
        int? toggle = null;
        (double, double, double)? range = null;
        var p = Pattern(e, UIA_ValuePatternId, IValuePattern);
        if (p != IntPtr.Zero)
        {
            IntPtr b;
            if (((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(p, 4 /* get_CurrentValue */))(p, &b) >= 0) value = Com.Bstr(b);
            Com.Release(p);
        }
        if (string.IsNullOrEmpty(value) && (p = Pattern(e, UIA_TogglePatternId, ITogglePattern)) != IntPtr.Zero)
        {
            int state;
            if (((delegate* unmanaged[Stdcall]<IntPtr, int*, int>)Com.Slot(p, 4 /* get_CurrentToggleState */))(p, &state) >= 0) toggle = state;
            Com.Release(p);
        }
        if (string.IsNullOrEmpty(value) && toggle is null && (p = Pattern(e, UIA_RangeValuePatternId, IRangeValuePattern)) != IntPtr.Zero)
        {
            double v, max, min;
            var get = (delegate* unmanaged[Stdcall]<IntPtr, double*, int>)Com.Slot(p, 4 /* get_CurrentValue */);
            var getMax = (delegate* unmanaged[Stdcall]<IntPtr, double*, int>)Com.Slot(p, 6 /* get_CurrentMaximum */);
            var getMin = (delegate* unmanaged[Stdcall]<IntPtr, double*, int>)Com.Slot(p, 7 /* get_CurrentMinimum */);
            if (get(p, &v) >= 0 && getMax(p, &max) >= 0 && getMin(p, &min) >= 0) range = (v, min, max);
            Com.Release(p);
        }
        if (string.IsNullOrEmpty(value) && toggle is null && range is null && (p = Pattern(e, UIA_TextPatternId, ITextPattern)) != IntPtr.Zero)
        {
            IntPtr doc;
            if (((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(p, 7 /* get_DocumentRange */))(p, &doc) >= 0 && doc != IntPtr.Zero)
            {
                IntPtr b;
                if (((delegate* unmanaged[Stdcall]<IntPtr, int, IntPtr*, int>)Com.Slot(doc, 12 /* GetText */))(doc, -1, &b) >= 0) value = Com.Bstr(b);
                Com.Release(doc);
            }
            Com.Release(p);
        }
        if (string.IsNullOrEmpty(value) && toggle is null && range is null && (p = Pattern(e, UIA_LegacyIAccessiblePatternId, ILegacyPattern)) != IntPtr.Zero)
        {
            IntPtr b;
            if (((delegate* unmanaged[Stdcall]<IntPtr, IntPtr*, int>)Com.Slot(p, 8 /* get_CurrentValue */))(p, &b) >= 0) value = Com.Bstr(b);
            Com.Release(p);
        }
        return DjayLabels.UiaText(value, toggle, range, control.Label);
    }

    // MARK: finding djay's window

    readonly Dictionary<int, string> _names = [];

    string ProcessName(int pid)
    {
        if (_names.TryGetValue(pid, out var n)) return n;
        try { n = Process.GetProcessById(pid).ProcessName; }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException) { n = ""; }
        if (_names.Count > 512) _names.Clear();
        return _names[pid] = n;
    }

    /// djay's top-level window: one of a program called djay…, or a Store app's frame whose title starts with "djay".
    IntPtr DjayWindow()
    {
        var found = IntPtr.Zero;
        var self = Environment.ProcessId;
        EnumWindows((hwnd, _) =>
        {
            if (!IsWindowVisible(hwnd)) return true;
            GetWindowThreadProcessId(hwnd, out var pid);
            if (pid == self) return true;
            var name = ProcessName((int)pid).ToLowerInvariant();
            if (name.Contains("djay") && !name.Contains("amadeus")) { found = hwnd; return false; }
            if (name == "applicationframehost")
            {
                var title = new char[64];
                var len = GetWindowText(hwnd, title, title.Length);
                if (new string(title, 0, Math.Max(0, len)).StartsWith("djay", StringComparison.OrdinalIgnoreCase)) { found = hwnd; return false; }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc proc, IntPtr param);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr hwnd, char[] text, int max);
}
