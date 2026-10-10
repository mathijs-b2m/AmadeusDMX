// Draws the app icon (a beam of light from a moving head over a dark stage) into an .iconset.
// swift tools/make-icon.swift OUT.iconset
import AppKit

let out = URL(fileURLWithPath: CommandLine.arguments[1])
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

func icon(_ px: Int) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(px), ctx = NSGraphicsContext.current!.cgContext
    // macOS icon grid: a rounded square inset ~10%
    let inset = s * 0.1, r = CGRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
    let shape = CGPath(roundedRect: r, cornerWidth: r.width * 0.225, cornerHeight: r.width * 0.225, transform: nil)
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -s * 0.01), blur: s * 0.03, color: CGColor(gray: 0, alpha: 0.5))
    ctx.addPath(shape); ctx.setFillColor(CGColor(red: 0.04, green: 0.04, blue: 0.08, alpha: 1)); ctx.fillPath()
    ctx.restoreGState()
    ctx.saveGState()
    ctx.addPath(shape); ctx.clip()
    let space = CGColorSpaceCreateDeviceRGB()
    let bg = CGGradient(colorsSpace: space, colors: [CGColor(red: 0.10, green: 0.05, blue: 0.22, alpha: 1),
                                                    CGColor(red: 0.01, green: 0.01, blue: 0.04, alpha: 1)] as CFArray, locations: [0, 1])!
    ctx.drawLinearGradient(bg, start: CGPoint(x: s / 2, y: r.maxY), end: CGPoint(x: s / 2, y: r.minY), options: [])
    // three beams fanning down from the top, in magenta, cyan and warm white
    let src = CGPoint(x: s * 0.5, y: r.maxY - s * 0.14)
    let beams: [(CGFloat, CGColor)] = [(-0.42, CGColor(red: 1, green: 0.1, blue: 0.75, alpha: 1)),
                                       (0.0, CGColor(red: 1, green: 0.95, blue: 0.85, alpha: 1)),
                                       (0.42, CGColor(red: 0.1, green: 0.85, blue: 1, alpha: 1))]
    ctx.setBlendMode(.screen)
    for (a, c) in beams {
        let len = s * 0.78, half: CGFloat = 0.09
        let p1 = CGPoint(x: src.x + sin(a - half) * len, y: src.y - cos(a - half) * len)
        let p2 = CGPoint(x: src.x + sin(a + half) * len, y: src.y - cos(a + half) * len)
        ctx.saveGState()
        ctx.move(to: src); ctx.addLine(to: p1); ctx.addLine(to: p2); ctx.closePath(); ctx.clip()
        let g = CGGradient(colorsSpace: space, colors: [c, c.copy(alpha: 0)!] as CFArray, locations: [0, 1])!
        ctx.drawRadialGradient(g, startCenter: src, startRadius: 0, endCenter: src, endRadius: len, options: [])
        ctx.restoreGState()
    }
    // the lens
    let lens = CGGradient(colorsSpace: space, colors: [CGColor(gray: 1, alpha: 1), CGColor(red: 1, green: 0.8, blue: 1, alpha: 0)] as CFArray,
                          locations: [0, 1])!
    ctx.drawRadialGradient(lens, startCenter: src, startRadius: 0, endCenter: src, endRadius: s * 0.09, options: [])
    // the stage floor
    ctx.setBlendMode(.normal)
    ctx.setFillColor(CGColor(red: 0.12, green: 0.12, blue: 0.2, alpha: 1))
    ctx.fill(CGRect(x: r.minX, y: r.minY, width: r.width, height: s * 0.1))
    ctx.restoreGState()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}

for (name, px) in [("16x16", 16), ("16x16@2x", 32), ("32x32", 32), ("32x32@2x", 64), ("128x128", 128),
                   ("128x128@2x", 256), ("256x256", 256), ("256x256@2x", 512), ("512x512", 512), ("512x512@2x", 1024)] {
    try icon(px).representation(using: .png, properties: [:])!.write(to: out.appendingPathComponent("icon_\(name).png"))
}
