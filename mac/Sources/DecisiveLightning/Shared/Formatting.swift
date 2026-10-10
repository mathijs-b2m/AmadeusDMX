// Small formatting helpers shared by the views.
import DecisiveKit
import SwiftUI

func timeString(_ t: Double) -> String {
    let s = max(0, Int(t))
    return String(format: "%d:%02d", s / 60, s % 60)
}

extension Color {
    init(simd c: SIMD3<Float>) { self.init(red: Double(c.x), green: Double(c.y), blue: Double(c.z)) }
}
