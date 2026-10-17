// What the show costs the computer, split between the light engine and the 3D stage: CPU use per process (the
// process's own CPU time, no admin rights needed), and the stage's GPU load (its measured GPU time when the renderer
// reports it, else Windows's GPU Engine counters for this app). No watts: Windows has no per-process estimate.
// The 3D stage can easily cost several times what the lights do; on a laptop or a smaller PC that matters during
// a gig, so the app shows it and suggests Perform Only when it adds up.
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace AmadeusKit;

public sealed class PowerMeter : Observable
{
    public readonly record struct Load(double Cpu = 0);  // share of one core, 0..n

    Load _engine, _stage;
    double _gpu;
    bool _onBattery, _lowPower, _hot, _measured;

    public Load Engine { get => _engine; private set => Set(ref _engine, value); }
    public Load Stage { get => _stage; private set => Set(ref _stage, value); }
    /// Share of the time the GPU spent drawing the 3D stage (0..1).
    public double Gpu { get => _gpu; private set => Set(ref _gpu, value); }
    public bool OnBattery { get => _onBattery; private set => Set(ref _onBattery, value); }
    /// Battery saver is on.
    public bool LowPower { get => _lowPower; private set => Set(ref _lowPower, value); }
    /// Getting hot (Windows tells apps nothing about it: always false here, kept for the Mac's rule).
    public bool Hot { get => _hot; private set => Set(ref _hot, value); }
    public bool Measured { get => _measured; private set => Set(ref _measured, value); }

    /// Seconds of GPU time the 3D stage has used so far (the renderer adds its frames' GPU time, when it measures it).
    public double GpuSeconds { get; set; }

    (double T, double? Engine, double? App, double Gpu)? _last;
    CancellationTokenSource? _timer;
    GpuCounter? _gpuCounter;

    public static readonly TimeSpan Interval = TimeSpan.FromSeconds(2);

    /// Start sampling `enginePid` (nil: no engine of ours, e.g. one started outside the app). The samples are
    /// taken on the thread that calls this (the UI thread in the app).
    public void Start(Func<int?> enginePid)
    {
        if (_timer is not null) return;
        _last = null;
        var cts = _timer = new CancellationTokenSource();
        if (OperatingSystem.IsWindows()) _gpuCounter ??= GpuCounter.ForThisProcess();
        _ = Run(enginePid, cts.Token);
    }

    async Task Run(Func<int?> enginePid, CancellationToken ct)
    {
        using var timer = new PeriodicTimer(Interval);
        try
        {
            while (await timer.WaitForNextTickAsync(ct)) Sample(enginePid());
        }
        catch (OperationCanceledException) { }
    }

    public void Stop()
    {
        _timer?.Cancel();
        _timer = null;
        Measured = false;
    }

    /// The 3D stage costs clearly more than the lights themselves (or the computer has little to spare).
    public bool StageIsHeavy => Measured && (Stage.Cpu + Gpu > 2 * Math.Max(Engine.Cpu, 0.05) || OnBattery || LowPower || Hot);

    void Sample(int? enginePid)
    {
        var now = Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
        var e = enginePid is { } pid ? Usage(pid) : null;
        var a = Usage(Environment.ProcessId);
        if (_last is { } l)
        {
            var dt = Math.Max(now - l.T, 1e-3);
            static Load L(double? x, double? y, double dt) => x is { } x0 && y is { } y0 ? new Load(Math.Max(0, (y0 - x0) / dt)) : new Load();
            Engine = L(l.Engine, e, dt);
            Stage = L(l.App, a, dt);
            Gpu = GpuSeconds > l.Gpu ? Math.Clamp((GpuSeconds - l.Gpu) / dt, 0, 1)
                : OperatingSystem.IsWindows() && _gpuCounter is { } g ? g.Sample() : 0;
            Measured = true;
        }
        _last = (now, e, a, GpuSeconds);
        if (OperatingSystem.IsWindows()) (OnBattery, LowPower) = Battery();
        Changed(nameof(StageIsHeavy));
    }

    /// CPU seconds a process has used so far; nil if it's gone (or not ours).
    internal static double? Usage(int pid)
    {
        try
        {
            using var p = Process.GetProcessById(pid);
            return p.TotalProcessorTime.TotalSeconds;
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or System.ComponentModel.Win32Exception
                                       or NotSupportedException) { return null; }
    }

    [StructLayout(LayoutKind.Sequential)]
    struct SystemPowerStatus
    {
        public byte ACLineStatus, BatteryFlag, BatteryLifePercent, SystemStatusFlag;
        public uint BatteryLifeTime, BatteryFullLifeTime;
    }

    [DllImport("kernel32.dll")]
    static extern bool GetSystemPowerStatus(out SystemPowerStatus status);

    /// On battery, and whether battery saver is on.
    [SupportedOSPlatform("windows")]
    static (bool, bool) Battery() =>
        GetSystemPowerStatus(out var s) ? (s.ACLineStatus == 0, s.SystemStatusFlag == 1) : (false, false);

    /// This app's 3D GPU engines' utilisation (PDH "GPU Engine" counters, as Task Manager shows them).
    [SupportedOSPlatform("windows")]
    sealed class GpuCounter
    {
        readonly string _path;
        IntPtr _query, _counter;
        DateTime _made;

        GpuCounter(string path) { _path = path; }

        public static GpuCounter ForThisProcess() => new($@"\GPU Engine(pid_{Environment.ProcessId}_*engtype_3D)\Utilization Percentage");

        /// 0..1 since the last sample. The engines show up once the app draws: the query is made again now and then.
        public double Sample()
        {
            if (_query == IntPtr.Zero || (DateTime.UtcNow - _made).TotalSeconds > 30) Open();
            if (_query == IntPtr.Zero || PdhCollectQueryData(_query) != 0) return 0;
            uint size = 0;
            if (PdhGetFormattedCounterArrayW(_counter, PDH_FMT_DOUBLE, ref size, out _, IntPtr.Zero) != PDH_MORE_DATA || size == 0) return 0;
            var buf = Marshal.AllocHGlobal((int)size);
            try
            {
                if (PdhGetFormattedCounterArrayW(_counter, PDH_FMT_DOUBLE, ref size, out var count, buf) != 0) return 0;
                double sum = 0;
                var item = Marshal.SizeOf<CounterItem>();
                for (var i = 0; i < count; i++)
                {
                    var it = Marshal.PtrToStructure<CounterItem>(buf + i * item);
                    if (it.CStatus == 0) sum += it.Value;
                }
                return Math.Clamp(sum / 100, 0, 1);
            }
            finally { Marshal.FreeHGlobal(buf); }
        }

        void Open()
        {
            if (_query != IntPtr.Zero) PdhCloseQuery(_query);
            _query = IntPtr.Zero;
            _made = DateTime.UtcNow;
            if (PdhOpenQueryW(null, IntPtr.Zero, out var q) != 0) return;
            if (PdhAddEnglishCounterW(q, _path, IntPtr.Zero, out _counter) != 0) { PdhCloseQuery(q); return; }
            _query = q;
            PdhCollectQueryData(q);  // rates need two samples: the first one is the baseline
        }

        const uint PDH_FMT_DOUBLE = 0x00000200;
        const uint PDH_MORE_DATA = 0x800007D2;

        [StructLayout(LayoutKind.Sequential)]
        struct CounterItem
        {
            public IntPtr Name;
            public uint CStatus;
            public double Value;  // PDH_FMT_COUNTERVALUE's union, as a double (8-aligned after CStatus)
        }

        [DllImport("pdh.dll", CharSet = CharSet.Unicode)] static extern uint PdhOpenQueryW(string? source, IntPtr user, out IntPtr query);
        [DllImport("pdh.dll", CharSet = CharSet.Unicode)] static extern uint PdhAddEnglishCounterW(IntPtr query, string path, IntPtr user, out IntPtr counter);
        [DllImport("pdh.dll")] static extern uint PdhCollectQueryData(IntPtr query);
        [DllImport("pdh.dll")] static extern uint PdhCloseQuery(IntPtr query);
        [DllImport("pdh.dll", CharSet = CharSet.Unicode)]
        static extern uint PdhGetFormattedCounterArrayW(IntPtr counter, uint format, ref uint size, out uint count, IntPtr buffer);
    }
}
