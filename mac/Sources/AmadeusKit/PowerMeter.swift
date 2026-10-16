// What the show costs the computer, split between the light engine and the 3D stage: CPU use per process
// (proc_pid_rusage: no admin rights needed), and the stage's GPU load (its own measured GPU time). No watts: the
// kernel's per-process estimate covers the CPU only, so it left out the GPU and compositing the 3D stage costs.
// The 3D stage can easily cost several times what the lights do; on a laptop or a smaller Mac that matters
// during a gig, so the app shows it and suggests Perform Only when it adds up.
import Darwin
import Foundation
import IOKit.ps
import Observation

@MainActor
@Observable
public final class PowerMeter {
    public struct Load: Equatable, Sendable {
        public var cpu: Double = 0  // share of one core, 0..n
    }

    public private(set) var engine = Load()
    public private(set) var stage = Load()
    /// Share of the time the GPU spent drawing the 3D stage (0..1).
    public private(set) var gpu: Double = 0
    public private(set) var onBattery = false
    public private(set) var lowPower = false
    public private(set) var hot = false
    public private(set) var measured = false

    /// Seconds of GPU time the 3D stage has used so far (the renderer adds its frames' GPU time).
    @ObservationIgnored public var gpuSeconds: Double = 0
    @ObservationIgnored private var last: (t: Double, engine: Double?, app: Double?, gpu: Double)?
    @ObservationIgnored private var timer: Timer?

    public static let interval: TimeInterval = 2

    public init() {}

    /// Start sampling `enginePid` (nil: no engine of ours, e.g. one started outside the app).
    public func start(enginePid: @escaping () -> Int32?) {
        guard timer == nil else { return }
        last = nil
        timer = Timer.scheduledTimer(withTimeInterval: Self.interval, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.sample(enginePid()) }
        }
    }

    public func stop() {
        timer?.invalidate()
        timer = nil
        measured = false
    }

    /// The 3D stage costs clearly more than the lights themselves (or the Mac has little to spare).
    public var stageIsHeavy: Bool {
        measured && (stage.cpu + gpu > 2 * max(engine.cpu, 0.05) || onBattery || lowPower || hot)
    }

    private func sample(_ enginePid: Int32?) {
        let now = ProcessInfo.processInfo.systemUptime
        let e = enginePid.flatMap(Self.usage), a = Self.usage(getpid())
        if let l = last {
            let dt = max(now - l.t, 1e-3)
            func load(_ x: Double?, _ y: Double?) -> Load {
                guard let x, let y else { return Load() }
                return Load(cpu: max(0, (y - x) / dt))
            }
            engine = load(l.engine, e)
            stage = load(l.app, a)
            gpu = min(1, max(0, (gpuSeconds - l.gpu) / dt))
            measured = true
        }
        last = (now, e, a, gpuSeconds)
        onBattery = Self.batteryPowered()
        lowPower = ProcessInfo.processInfo.isLowPowerModeEnabled
        hot = ProcessInfo.processInfo.thermalState.rawValue >= ProcessInfo.ThermalState.serious.rawValue
    }

    /// CPU seconds a process has used so far; nil if it's gone (or not ours).
    nonisolated static func usage(_ pid: Int32) -> Double? {
        var info = rusage_info_v6()
        let ok = withUnsafeMutablePointer(to: &info) { p in
            p.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_V6, $0) }
        }
        guard ok == 0 else { return nil }
        var tb = mach_timebase_info_data_t()
        mach_timebase_info(&tb)
        return Double(info.ri_user_time + info.ri_system_time) * Double(tb.numer) / Double(tb.denom) / 1e9
    }

    nonisolated static func batteryPowered() -> Bool {
        guard let blob = IOPSCopyPowerSourcesInfo()?.takeRetainedValue(),
              let type = IOPSGetProvidingPowerSourceType(blob)?.takeUnretainedValue() else { return false }
        return (type as String) == kIOPSBatteryPowerValue
    }
}
