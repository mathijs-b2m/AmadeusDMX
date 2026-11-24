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
