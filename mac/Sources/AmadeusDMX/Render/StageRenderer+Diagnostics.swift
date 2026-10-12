// Development: GPU time, frame rates and exposure, logged to $TMPDIR/gpu-stats.txt with -gpuStats YES.
import AmadeusKit
import Metal
import MetalKit
import MetalPerformanceShaders
import QuartzCore
import simd

extension StageRenderer {
    static let gpuStats = UserDefaults.standard.bool(forKey: "gpuStats")
    static var gpuSamples: [Double] = []
    static var nanCheckAt = Date.distantPast
    static var lastLum: Float = 0, lastExposure: Float = 1
    static var lastFrameT = -1.0
    static var newFrames = 0
    static var gpuSince = Date()

    static func recordGPU(_ ms: Double, beams: Int, size: CGSize) {
        gpuSamples.append(ms)
        guard Date().timeIntervalSince(gpuSince) > 3 else { return }
        let avg = gpuSamples.reduce(0, +) / Double(gpuSamples.count)
        let line = String(format: "%.1f ms GPU/frame (max %.1f), %.0f drawn/s, %.0f new show frames/s, %d beams, %.0f×%.0f px, light %.2f → exposure %.2f\n",
                          avg, gpuSamples.max() ?? 0, Double(gpuSamples.count) / 3, Double(newFrames) / 3, beams, size.width, size.height,
                          lastLum, lastExposure)
        newFrames = 0
        let url = FileManager.default.temporaryDirectory.appending(path: "gpu-stats.txt")
        if let h = try? FileHandle(forWritingTo: url) { h.seekToEndOfFile(); h.write(Data(line.utf8)); try? h.close() }
        else { try? line.write(to: url, atomically: true, encoding: .utf8) }
        gpuSamples = []; gpuSince = Date()
    }
}
