// The LED wall output's geometry: the wall's rectangle on the display, the picture fitted into it, how fine it is
// drawn, and the settings read back with defaults.
import Foundation
import Testing

@testable import AmadeusKit

@Test func theWallIsTheWholeDisplayUnlessSet() {
    #expect(WallOutputLayout.wallRect(nil, display: 1920, 1080) == PixelRect(x: 0, y: 0, w: 1920, h: 1080))
    // a 6×3 wall of 128 px panels at the processor's start position
    #expect(WallOutputLayout.wallRect(PixelRect(x: 0, y: 0, w: 768, h: 384), display: 1920, 1080)
        == PixelRect(x: 0, y: 0, w: 768, h: 384))
}

@Test func aWallOffTheDisplayIsKeptOnIt() {
    #expect(WallOutputLayout.wallRect(PixelRect(x: 1800, y: 1000, w: 768, h: 384), display: 1920, 1080)
        == PixelRect(x: 1800, y: 1000, w: 120, h: 80))
    #expect(WallOutputLayout.wallRect(PixelRect(x: -50, y: 5000, w: 0, h: 10), display: 1920, 1080)
        == PixelRect(x: 0, y: 1079, w: 1, h: 1))
}

@Test func thePictureIsFittedAndCentred() {
    // 16:9 fills; a 2:1 wall gets bars left and right, a tall one above and below
    #expect(WallOutputLayout.fit(PixelRect(x: 0, y: 0, w: 1920, h: 1080)) == PixelRect(x: 0, y: 0, w: 1920, h: 1080))
    #expect(WallOutputLayout.fit(PixelRect(x: 0, y: 0, w: 768, h: 384)) == PixelRect(x: 42, y: 0, w: 683, h: 384))
    #expect(WallOutputLayout.fit(PixelRect(x: 100, y: 0, w: 512, h: 768)) == PixelRect(x: 100, y: 240, w: 512, h: 288))
    // a pixel off 16:9 is filled, no hairline bars
    #expect(WallOutputLayout.fit(PixelRect(x: 0, y: 0, w: 1366, h: 768)) == PixelRect(x: 0, y: 0, w: 1366, h: 768))
}

@Test func thePictureIsDrawnAsFineAsTheWallNeeds() {
    #expect(WallOutputLayout.pictureScale(forWallHeight: nil) == 1)
    #expect(WallOutputLayout.pictureScale(forWallHeight: 288) == 1)
    #expect(WallOutputLayout.pictureScale(forWallHeight: 384) == 1.5)
    #expect(WallOutputLayout.pictureScale(forWallHeight: 540) == 1.5)
    #expect(WallOutputLayout.pictureScale(forWallHeight: 2160) == 2)
}

@Test func aHiDPIModeDrawsTheRectangleInItsOwnPixels() {
    let r = PixelRect(x: 10, y: 20, w: 768, h: 384)
    #expect(WallOutputLayout.scaled(r, from: (1920, 1080), to: (1920, 1080)) == r)
    #expect(WallOutputLayout.scaled(r, from: (1920, 1080), to: (3840, 2160)) == PixelRect(x: 20, y: 40, w: 1536, h: 768))
}

@Test func panelsMakeTheWall() {
    #expect(WallOutputLayout.panels(cols: 6, rows: 3, panelPx: 128) == PixelRect(x: 0, y: 0, w: 768, h: 384))
}

@Test func settingsReadBackWithTheirDefaults() throws {
    let s = try JSONDecoder().decode(WallOutputSettings.self, from: Data(#"{"on": true, "leadMs": 900, "brightness": 2}"#.utf8))
    #expect(s.on && s.target == .display && s.rect == nil && s.panelPx == 128 && !s.testPattern)
    #expect(s.leadMs == 200 && s.brightness == 1)  // kept in range
    let odd = try JSONDecoder().decode(WallOutputSettings.self, from: Data(#"{"target": "projector"}"#.utf8))
    #expect(odd.target == .display)

    var t = WallOutputSettings()
    t.on = true; t.target = .window; t.display = "UUID"; t.rect = PixelRect(x: 0, y: 0, w: 768, h: 384); t.leadMs = -40
    let d = try #require(UserDefaults(suiteName: "wall-output-test-\(UUID().uuidString)"))
    t.save(d)
    #expect(WallOutputSettings.load(d) == t)
}

@Test func theWallsShapeComesFromItsPixels() throws {
    #expect(ScreenShape.pixels(nil) == nil)
    #expect(ScreenShape.pixels(.bool(true)) == nil)
    let px = try #require(ScreenShape.pixels(.object(["pixels": .array([.number(768), .number(384)])])))
    #expect(px.w == 768 && px.h == 384 && ScreenShape.aspect(px) == 2)
    #expect(ScreenShape.aspect(nil) == 16.0 / 9.0)
    #expect(ScreenShape.aspect((w: 10000, h: 10)) == 6)   // kept in range
    // a tall wall stays under the ceiling, its shape kept; 16:9 and wider as always
    let tall = ScreenShape.size(width: 5, aspect: 0.5, bottom: 1.4, ceiling: 6)
    #expect(abs(tall.h - 4.3) < 1e-9 && abs(tall.w - 2.15) < 1e-9)
    let wide = ScreenShape.size(width: 8, aspect: 16.0 / 9.0, bottom: 1.4, ceiling: 3)
    #expect(wide.w == 8 && wide.h == 4.5)
}

@Test func theHelloCarriesTheWallsPixels() throws {
    let json = #"{"type": "hello", "screen": true, "screen_px": [1536, 384]}"#
    guard case .hello(let h) = try #require(FeedMessage.decode(Data(json.utf8))) else { Issue.record("not a hello"); return }
    #expect(h.screenPx == [1536, 384] && h.screenAspect == 4)
    guard case .hello(let old) = try #require(FeedMessage.decode(Data(#"{"type": "hello", "screen": true}"#.utf8))) else { return }
    #expect(old.screenPx == nil && old.screenAspect == 16.0 / 9.0)
}

@Test func aLongWallIsDrawnFineEnoughButNotTooBig() {
    #expect(WallOutputLayout.pictureScale(picture: nil, canvas: (640, 360)) == 1)
    #expect(WallOutputLayout.pictureScale(picture: PixelRect(x: 0, y: 0, w: 1920, h: 1080), canvas: (640, 360)) == 2)
    #expect(WallOutputLayout.pictureScale(picture: PixelRect(x: 0, y: 0, w: 768, h: 384), canvas: (720, 360)) == 1.5)
    // a 4:1 ribbon of 2560 × 640: 1440 × 360 units at 2 would be 2 million pixels for the CPU
    #expect(WallOutputLayout.pictureScale(picture: PixelRect(x: 0, y: 0, w: 2560, h: 640), canvas: (1440, 360)) == 1.5)
}
