// Runs the Python engine (`python -m amadeus …`) as a child process: start, stop (cleanly first, so the engine
// blacks out the lights itself), and its output line by line for the log.
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;

namespace AmadeusKit;

public enum EngineStateKind { Stopped, Starting, Running, Failed }

/// stopped, starting, running, or failed with the reason (Swift: `case failed(String)`).
public readonly record struct EngineState(EngineStateKind Kind, string Reason = "")
{
    public static readonly EngineState Stopped = new(EngineStateKind.Stopped);
    public static readonly EngineState Starting = new(EngineStateKind.Starting);
    public static readonly EngineState Running = new(EngineStateKind.Running);
    public static EngineState Failed(string why) => new(EngineStateKind.Failed, why);
}

public sealed class EngineProcess : Observable
{
    public sealed record LogLine(int Id, DateTime Date, string Text, bool IsError);

    public string Name { get; }
    EngineState _state = EngineState.Stopped;
    public EngineState State
    {
        get => _state;
        private set { if (Set(ref _state, value)) Changed(nameof(IsRunning)); }
    }

    readonly List<LogLine> _log = [];
    /// The log (the last 4000 lines). `LogChanged` says when it grew (a PropertyChanged per line would be too many).
    public IReadOnlyList<LogLine> Log => _log;
    public event Action? LogChanged;

    IReadOnlyList<string> _arguments = [];
    public IReadOnlyList<string> Arguments { get => _arguments; private set => Set(ref _arguments, value); }
    string _lastLine = "";
    /// The last line the engine printed (for a status line).
    public string LastLine { get => _lastLine; private set => Set(ref _lastLine, value); }

    Process? _process;
    int _nextID;
    string? _readyMarker;
    bool _keptAwake;
    bool _stopRequested;
    readonly UIThread _ui;
    public Action<string>? OnLine { get; set; }

    public EngineProcess(string name, SynchronizationContext? context = null)
    {
        Name = name;
        _ui = new UIThread(context ?? SynchronizationContext.Current);
    }

    /// The engine's process id while it runs (for the power meter).
    public int? Pid
    {
        get
        {
            try { return _process is { HasExited: false } p ? p.Id : null; }
            catch (InvalidOperationException) { return null; }
        }
    }

    public bool IsRunning => State.Kind is EngineStateKind.Running or EngineStateKind.Starting;

    /// Starts `python -m amadeus <args>` in the workspace. `readyWhen`: a text in the output that means the
    /// engine is up (until then the state is Starting).
    public void Start(Workspace ws, IReadOnlyList<string> args, IReadOnlyDictionary<string, string>? environment = null,
                      string? readyWhen = null, bool keepAwake = false)
    {
        if (IsRunning) return;
        var psi = new ProcessStartInfo(ws.Python)
        {
            WorkingDirectory = ws.Root,
            UseShellExecute = false,
            RedirectStandardInput = true,   // closing it is the first way to ask the engine to stop (StopGracefully)
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
        };
        // its own process group: a Ctrl+Break for it reaches it alone, never this app (Windows)
        if (OperatingSystem.IsWindows()) psi.CreateNewProcessGroup = true;
        psi.ArgumentList.Add("-m");
        psi.ArgumentList.Add("amadeus");
        foreach (var a in args) psi.ArgumentList.Add(a);
        psi.Environment["PYTHONUNBUFFERED"] = "1";
        psi.Environment["PYTHONIOENCODING"] = "utf-8";
        foreach (var (k, v) in environment ?? new Dictionary<string, string>()) psi.Environment[k] = v;

        var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
        p.Exited += (_, _) => _ui.Post(() => Ended(p));
        Arguments = args;
        _readyMarker = readyWhen;
        _stopRequested = false;
        Append($"$ amadeus {string.Join(' ', args)}", isError: false);
        try
        {
            p.Start();
        }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException or FileNotFoundException)
        {
            State = EngineState.Failed(e.Message);
            Append($"could not start: {e.Message}", isError: true);
            return;
        }
        _process = p;
        _ = Pump(p.StandardOutput, isError: false);
        _ = Pump(p.StandardError, isError: true);
        Remember(p, Name);
        State = readyWhen is null ? EngineState.Running : EngineState.Starting;
        if (keepAwake)
        {
            // the light loop must tick 40 times a second on time: above normal priority, and never throttled
            // (EcoQoS) while the app is in the background, e.g. while you work in VirtualDJ
            try { p.PriorityClass = ProcessPriorityClass.AboveNormal; }
            catch (Exception e) when (e is Win32Exception or InvalidOperationException) { }
            if (OperatingSystem.IsWindows())
            {
                Win32.NoThrottling(p);
                Win32.KeepAwake(true);  // like `caffeinate -i`: no idle sleep while a show runs, the display may still sleep
                _keptAwake = true;
            }
        }
    }

    /// Reads one of the engine's outputs line by line ("\r" dropped, like the Mac's log).
    async Task Pump(StreamReader reader, bool isError)
    {
        var buf = new StringBuilder();
        var chunk = new char[4096];
        try
        {
            int n;
            while ((n = await reader.ReadAsync(chunk, 0, chunk.Length).ConfigureAwait(false)) > 0)
            {
                buf.Append(chunk, 0, n);
                var lines = new List<string>();
                int nl;
                while ((nl = IndexOf(buf, '\n')) >= 0)
                {
                    var line = buf.ToString(0, nl).Replace("\r", "");
                    buf.Remove(0, nl + 1);
                    if (line.Length > 0) lines.Add(line);
                }
                if (lines.Count > 0) _ui.Post(() => { foreach (var l in lines) Append(l, isError && LooksLikeError(l)); });
            }
        }
        catch (Exception e) when (e is IOException or ObjectDisposedException or InvalidOperationException) { }
    }

    static int IndexOf(StringBuilder sb, char c)
    {
        for (var i = 0; i < sb.Length; i++) if (sb[i] == c) return i;
        return -1;
    }

    /// Asks the engine to stop (it blacks out the lights itself), then ends it if it doesn't.
    public void Stop()
    {
        if (_process is not { } p || HasExited(p)) { State = EngineState.Stopped; return; }
        _ = StopGracefully(p);
    }

    /// Stops and waits until the process has ended (e.g. before quitting the app). Blocks: only for quitting.
    public void StopAndWait(double timeout = 5)
    {
        if (_process is not { } p || HasExited(p)) return;
        var stop = StopGracefully(p, killAfter: timeout);
        try { stop.Wait(TimeSpan.FromSeconds(timeout + 1)); }
        catch (AggregateException) { }
    }

    // contract: how the app asks the engine to stop cleanly on Windows. The engine stops (and blacks out) when its
    // stdin closes, and on Ctrl+Break (SIGBREAK; the engine runs in a process group of its own). Off Windows it is
    // Ctrl-C (SIGINT), as on the Mac. Whatever is still running after `killAfter` seconds is ended.
    public Task StopGracefully() => _process is { } p && !HasExited(p) ? StopGracefully(p) : Task.CompletedTask;

    async Task StopGracefully(Process p, double breakAfter = 1.5, double killAfter = 5)
    {
        _stopRequested = true;
        try { p.StandardInput.Close(); }
        catch (Exception e) when (e is IOException or InvalidOperationException) { }
        if (!OperatingSystem.IsWindows()) Unix.Interrupt(p.Id);
        var started = Stopwatch.StartNew();
        var broke = !OperatingSystem.IsWindows();
        while (!HasExited(p) && started.Elapsed.TotalSeconds < killAfter)
        {
            if (!broke && started.Elapsed.TotalSeconds >= breakAfter)
            {
                broke = true;
                if (OperatingSystem.IsWindows()) Win32.CtrlBreak(p.Id);
            }
            await Task.Delay(50).ConfigureAwait(false);
        }
        if (!HasExited(p))
            try { p.Kill(entireProcessTree: true); }
            catch (Exception e) when (e is Win32Exception or InvalidOperationException) { }
    }

    static bool HasExited(Process p)
    {
        try { return p.HasExited; }
        catch (InvalidOperationException) { return true; }
    }

    public void ClearLog()
    {
        _log.Clear();
        LogChanged?.Invoke();
    }

    // MARK: engines left behind

    static string PidKey(string name) => $"enginePID.{name}";

    /// The pid and its start time: a pid alone may belong to another program by now.
    static void Remember(Process? p, string name)
    {
        if (p is null) { Defaults.Standard.Remove(PidKey(name)); return; }
        try { Defaults.Standard.Set(PidKey(name), $"{p.Id}:{p.StartTime.ToUniversalTime().Ticks}"); }
        catch (Exception e) when (e is Win32Exception or InvalidOperationException) { }
    }

    /// An engine this app started before and that outlived it (the app crashed or was killed): stop it, so it
    /// doesn't keep driving the lights or hold the ports. Only if that pid is still the process we started.
    public static void StopLeftover(string name)
    {
        var saved = Defaults.Standard.String(PidKey(name))?.Split(':');
        Remember(null, name);
        if (saved is not [var pidText, var ticksText] || !int.TryParse(pidText, out var pid) || !long.TryParse(ticksText, out var ticks))
            return;
        try
        {
            using var p = Process.GetProcessById(pid);
            if (p.StartTime.ToUniversalTime().Ticks != ticks) return;
            if (OperatingSystem.IsWindows()) Win32.CtrlBreak(pid); else Unix.Interrupt(pid);
            if (!p.WaitForExit(4000)) p.Kill(entireProcessTree: true);
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or Win32Exception) { }
    }

    static bool LooksLikeError(string line)
    {
        var l = line.ToLowerInvariant();
        return l.Contains("error") || l.Contains("traceback") || l.Contains("exception");
    }

    void Append(string line, bool isError)
    {
        _log.Add(new LogLine(_nextID, DateTime.Now, line, isError));
        _nextID++;
        if (_log.Count > 4000) _log.RemoveRange(0, _log.Count - 4000);
        LastLine = line;
        if (State.Kind == EngineStateKind.Starting && _readyMarker is { } m && line.Contains(m)) State = EngineState.Running;
        LogChanged?.Invoke();
        OnLine?.Invoke(line);
    }

    void Ended(Process p)
    {
        if (!ReferenceEquals(p, _process)) return;
        _process = null;
        Remember(null, Name);
        if (_keptAwake && OperatingSystem.IsWindows()) { Win32.KeepAwake(false); _keptAwake = false; }
        int code;
        try { code = p.ExitCode; }
        catch (InvalidOperationException) { code = -1; }
        // 130 / 2 + KeyboardInterrupt: Ctrl-C; 0xC000013A: ended by Ctrl+Break / Ctrl-C on Windows; asked to stop
        var clean = code == 0 || _stopRequested || code == 130 || code == unchecked((int)0xC000013A)
                    || (code == 2 && LastLine.Contains("KeyboardInterrupt"));
        if (clean || (_log.Count > 0 && _log[^1].Text.Contains("KeyboardInterrupt")))
        {
            State = EngineState.Stopped;
            Append("engine stopped", isError: false);
        }
        else
        {
            var why = _log.LastOrDefault(l => l.IsError)?.Text ?? LastLine;
            State = EngineState.Failed(why);
            Append($"engine exited with code {code}", isError: true);
        }
        p.Dispose();
    }

    // MARK: the system

    static class Unix
    {
        [DllImport("libc", EntryPoint = "kill", SetLastError = true)]
        static extern int kill(int pid, int sig);

        public static void Interrupt(int pid) => kill(pid, 2);  // SIGINT
    }

    [SupportedOSPlatform("windows")]
    static class Win32
    {
        const uint CTRL_BREAK_EVENT = 1;
        const uint ATTACH_PARENT_PROCESS = unchecked((uint)-1);
        static readonly Lock ConsoleLock = new();

        [DllImport("kernel32.dll", SetLastError = true)] static extern bool AttachConsole(uint pid);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool FreeConsole();
        [DllImport("kernel32.dll")] static extern IntPtr GetConsoleWindow();
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool SetConsoleCtrlHandler(IntPtr handler, bool add);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool GenerateConsoleCtrlEvent(uint ctrlEvent, uint processGroupId);
        [DllImport("kernel32.dll")] static extern uint SetThreadExecutionState(uint flags);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetProcessInformation(IntPtr process, int infoClass, ref PowerThrottlingState info, int size);

        [StructLayout(LayoutKind.Sequential)]
        struct PowerThrottlingState { public uint Version, ControlMask, StateMask; }

        /// Ctrl+Break to the engine's process group. A console event only reaches processes on the sender's
        /// console, and the engine has a (hidden) console of its own: join it for the moment it takes, ignoring
        /// the event here.
        public static void CtrlBreak(int pid)
        {
            lock (ConsoleLock)
            {
                var hadConsole = GetConsoleWindow() != IntPtr.Zero;  // started from a terminal (development)
                if (hadConsole) FreeConsole();
                if (AttachConsole((uint)pid))
                {
                    SetConsoleCtrlHandler(IntPtr.Zero, true);
                    GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, (uint)pid);
                    FreeConsole();
                    Thread.Sleep(10);  // the event is delivered on another thread: keep ignoring it a moment
                    SetConsoleCtrlHandler(IntPtr.Zero, false);
                }
                if (hadConsole) AttachConsole(ATTACH_PARENT_PROCESS);
            }
        }

        /// No idle sleep (the display may still sleep); called on the UI thread, which lives as long as the app.
        public static void KeepAwake(bool on)
        {
            const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x1;
            SetThreadExecutionState(on ? ES_CONTINUOUS | ES_SYSTEM_REQUIRED : ES_CONTINUOUS);
        }

        /// Opts the engine out of power throttling (EcoQoS) and timer coalescing.
        public static void NoThrottling(Process p)
        {
            const int ProcessPowerThrottling = 4;
            const uint EXECUTION_SPEED = 0x1, IGNORE_TIMER_RESOLUTION = 0x4;
            var s = new PowerThrottlingState { Version = 1, ControlMask = EXECUTION_SPEED | IGNORE_TIMER_RESOLUTION, StateMask = 0 };
            try { SetProcessInformation(p.Handle, ProcessPowerThrottling, ref s, Marshal.SizeOf<PowerThrottlingState>()); }
            catch (InvalidOperationException) { }
        }
    }
}
