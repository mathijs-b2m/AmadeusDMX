// The LED wall output (the app's LED Wall Output window): where the wall's picture goes on this computer, and the
// geometry of putting it there. An LED processor (NovaStar and the like) takes one video signal, say 1920×1080 over
// HDMI, and reads the wall's own pixels from a rectangle of it, one to one. So the output draws the picture into
// exactly that rectangle of the display, black around it, and never scales the display itself.
//
// These settings belong to the computer (which display is the HDMI out), not to a set or a rig: they live in the
// app's defaults. The picture is 16:9 (WallRenderer); a wall of another shape shows it fitted, black bars aside.
import Foundation

/// A rectangle in pixels, from the top left.
public struct PixelRect: Codable, Equatable, Hashable, Sendable {
    public var x: Int, y: Int, w: Int, h: Int
    public init(x: Int, y: Int, w: Int, h: Int) { self.x = x; self.y = y; self.w = w; self.h = h }
}

public struct WallOutputSettings: Codable, Equatable, Sendable {
    public enum Target: String, Codable, CaseIterable, Sendable {
        case display   // full screen on a display (the HDMI into the LED processor)
        case window    // in a window on this screen: try it without a second display, or for a capture (OBS)
    }

    public var on = false
    public var target: Target = .display
    /// The display, by its UUID (stays the same across restarts and plugging in again).
    public var display: String?
    /// Its name, for the window while it is not connected.
    public var displayName: String?
    /// The wall in the display's pixels; nil: the whole display.
    public var rect: PixelRect?
    /// A ceiling on the wall's brightness, 0..1 (LED walls are bright: a dark club wants far less than daylight).
    public var brightness: Double = 1
    /// Milliseconds the picture runs ahead of the lights: an LED processor holds a frame or two (positive values
    /// win that back), a slow DMX node the other way.
    public var leadMs: Double = 0
    /// A test card instead of the show: the rectangle's edges, the panel grid, colour bars, a moving bar.
    public var testPattern = false
    /// One LED panel's size in pixels (the test card's grid).
    public var panelPx: Int = 128

    public static let defaultsKey = "ledWallOutput"
    public static let leadRange: ClosedRange<Double> = -200...200
    public static let panelRange: ClosedRange<Int> = 16...1024

    public init() {}

    enum CodingKeys: String, CodingKey { case on, target, display, displayName, rect, brightness, leadMs, testPattern, panelPx }

    // missing keys keep their defaults (older or hand-written settings)
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        on = try c.decodeIfPresent(Bool.self, forKey: .on) ?? false
        target = (try? c.decodeIfPresent(Target.self, forKey: .target)) ?? .display
        display = try c.decodeIfPresent(String.self, forKey: .display)
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName)
        rect = try c.decodeIfPresent(PixelRect.self, forKey: .rect)
        brightness = min(1, max(0, try c.decodeIfPresent(Double.self, forKey: .brightness) ?? 1))
        leadMs = min(Self.leadRange.upperBound, max(Self.leadRange.lowerBound, try c.decodeIfPresent(Double.self, forKey: .leadMs) ?? 0))
        testPattern = try c.decodeIfPresent(Bool.self, forKey: .testPattern) ?? false
        panelPx = min(Self.panelRange.upperBound, max(Self.panelRange.lowerBound, try c.decodeIfPresent(Int.self, forKey: .panelPx) ?? 128))
    }

    public static func load(_ defaults: UserDefaults = .standard) -> WallOutputSettings {
        guard let data = defaults.data(forKey: defaultsKey),
              let s = try? JSONDecoder().decode(WallOutputSettings.self, from: data) else { return WallOutputSettings() }
        return s
    }

    public func save(_ defaults: UserDefaults = .standard) {
        if let data = try? JSONEncoder().encode(self) { defaults.set(data, forKey: Self.defaultsKey) }
    }
}

public enum WallOutputLayout {
    /// The wall's picture: 16:9.
    public static let aspect = 16.0 / 9.0

    /// The wall on a display of `width`×`height` pixels: the setting, kept on the display (at least 1×1), or the
    /// whole display.
    public static func wallRect(_ r: PixelRect?, display width: Int, _ height: Int) -> PixelRect {
        let W = max(1, width), H = max(1, height)
        guard let r else { return PixelRect(x: 0, y: 0, w: W, h: H) }
        let x = min(max(0, r.x), W - 1), y = min(max(0, r.y), H - 1)
        return PixelRect(x: x, y: y, w: min(max(1, r.w), W - x), h: min(max(1, r.h), H - y))
    }

    /// Where a picture of `aspect` goes inside the wall: as big as fits, centred, in whole pixels. A wall a pixel
    /// off 16:9 is filled (no hairline bars).
    public static func fit(_ wall: PixelRect, aspect: Double = aspect) -> PixelRect {
        let wa = Double(wall.w) / Double(max(1, wall.h))
        var w = wall.w, h = wall.h
        if wa > aspect { w = Int((Double(wall.h) * aspect).rounded()) } else { h = Int((Double(wall.w) / aspect).rounded()) }
        if wall.w - w <= 2 { w = wall.w }
        if wall.h - h <= 2 { h = wall.h }
        return PixelRect(x: wall.x + (wall.w - w) / 2, y: wall.y + (wall.h - h) / 2, w: max(1, w), h: max(1, h))
    }

    /// How much finer than 640×360 the picture is drawn: 1 for the 3D stage alone, up to 2 (1280×720) for a big
    /// wall. The figures are lines, sharp at any size; the CPU draws them, so not finer than the wall needs.
    public static func pictureScale(forWallHeight h: Int?) -> Double {
        guard let h, h > 0 else { return 1 }
        return min(2, max(1, (Double(h) / 360 * 2).rounded(.up) / 2))
    }

    /// A rectangle in the display's own pixels, in the pixels of what is drawn (a HiDPI mode draws more pixels than
    /// it sends; the window's drawable is in those).
    public static func scaled(_ r: PixelRect, from mode: (w: Int, h: Int), to drawable: (w: Int, h: Int)) -> PixelRect {
        let kx = Double(drawable.w) / Double(max(1, mode.w)), ky = Double(drawable.h) / Double(max(1, mode.h))
        let x = Int((Double(r.x) * kx).rounded()), y = Int((Double(r.y) * ky).rounded())
        let x1 = Int((Double(r.x + r.w) * kx).rounded()), y1 = Int((Double(r.y + r.h) * ky).rounded())
        return PixelRect(x: x, y: y, w: max(1, x1 - x), h: max(1, y1 - y))
    }

    /// A wall of `cols`×`rows` panels of `panelPx`, from the top left of the display.
    public static func panels(cols: Int, rows: Int, panelPx: Int) -> PixelRect {
        PixelRect(x: 0, y: 0, w: max(1, cols) * max(1, panelPx), h: max(1, rows) * max(1, panelPx))
    }
}
