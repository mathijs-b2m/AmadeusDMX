// The LED wall's test card (LED Wall Output › Test Card), to line the output up with the LED processor: the panel
// grid from the wall's top left with each panel's column and row, a one-pixel white edge with a coloured corner at
// each end (top left red, top right green, bottom left blue, bottom right yellow: a mirrored or turned map shows at
// once), diagonals and a circle (a stretched picture makes it an oval), colour bars and a grey ramp. The output's
// shader adds a bar that crosses every two seconds: it tears or stutters when frames are dropped.
import CoreGraphics
import CoreText
import AmadeusKit
import Foundation

enum TestCard {
    /// The card at `pixels` (the wall's rectangle in what is drawn), labelled with `wall` (its rectangle in the
    /// display's own pixels, what the processor is told).
    static func draw(pixels: (w: Int, h: Int), wall: PixelRect, panelPx: Int) -> CGImage? {
        let W = max(1, pixels.w), H = max(1, pixels.h)
        guard let g = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W * 4,
                                space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)
        else { return nil }
        g.translateBy(x: 0, y: CGFloat(H))
        g.scaleBy(x: 1, y: -1)   // y down, from the top left like the display
        let k = CGFloat(W) / CGFloat(max(1, wall.w))   // drawn pixels per display pixel (2 in a HiDPI mode)
        let w = CGFloat(W), h = CGFloat(H), px = 1 * k
        g.setFillColor(CGColor(gray: 0, alpha: 1))
        g.fill(CGRect(x: 0, y: 0, width: w, height: h))

        // colour bars across the middle, a grey ramp under them
        let bars: [(CGFloat, CGFloat, CGFloat)] = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)]
        let by = h * 0.36, bh = h * 0.2, bw = w / CGFloat(bars.count)
        for (i, c) in bars.enumerated() {
            g.setFillColor(CGColor(srgbRed: c.0 * 0.85, green: c.1 * 0.85, blue: c.2 * 0.85, alpha: 1))
            g.fill(CGRect(x: CGFloat(i) * bw, y: by, width: bw + 1, height: bh))
        }
        let steps = 16
        for i in 0..<steps {
            g.setFillColor(CGColor(gray: CGFloat(i) / CGFloat(steps - 1), alpha: 1))
            g.fill(CGRect(x: w * CGFloat(i) / CGFloat(steps), y: by + bh, width: w / CGFloat(steps) + 1, height: h * 0.08))
        }

        // the panels: a grid from the top left, each with its column and row
        let p = CGFloat(max(1, panelPx)) * k
        g.setStrokeColor(CGColor(gray: 0.45, alpha: 1))
        g.setLineWidth(px)
        var x: CGFloat = p
        while x < w - 0.5 { g.stroke(CGRect(x: x + px / 2, y: -px, width: 0, height: h + 2 * px)); x += p }
        var y: CGFloat = p
        while y < h - 0.5 { g.stroke(CGRect(x: -px, y: y + px / 2, width: w + 2 * px, height: 0)); y += p }
        if p >= 40 {
            let size = min(p * 0.16, 28 * k)
            for c in 0..<Int((w / p).rounded(.up)) {
                for r in 0..<Int((h / p).rounded(.up)) {
                    text(g, "\(c + 1),\(r + 1)", at: CGPoint(x: CGFloat(c) * p + 4 * k, y: CGFloat(r) * p + 4 * k), size: size,
                         gray: 0.6, centred: false)
                }
            }
        }

        // diagonals and a circle: lines meet in the middle, the circle stays round on the wall
        g.setStrokeColor(CGColor(gray: 0.7, alpha: 1))
        g.setLineWidth(px)
        g.strokeLineSegments(between: [CGPoint(x: 0, y: 0), CGPoint(x: w, y: h), CGPoint(x: w, y: 0), CGPoint(x: 0, y: h)])
        let d = min(w, h) * 0.8
        g.setLineWidth(2 * px)
        g.setStrokeColor(CGColor(gray: 1, alpha: 1))
        g.strokeEllipse(in: CGRect(x: (w - d) / 2, y: (h - d) / 2, width: d, height: d))

        // the edge, one pixel, and the corners
        g.setStrokeColor(CGColor(gray: 1, alpha: 1))
        g.setLineWidth(px)
        g.stroke(CGRect(x: px / 2, y: px / 2, width: w - px, height: h - px))
        let arm = min(w, h) * 0.12, thick = max(3 * k, min(w, h) * 0.015)
        let corners: [(CGPoint, CGFloat, CGFloat, (CGFloat, CGFloat, CGFloat))] = [
            (CGPoint(x: 0, y: 0), 1, 1, (1, 0, 0)), (CGPoint(x: w, y: 0), -1, 1, (0, 1, 0)),
            (CGPoint(x: 0, y: h), 1, -1, (0, 0.4, 1)), (CGPoint(x: w, y: h), -1, -1, (1, 0.9, 0)),
        ]
        for (o, sx, sy, c) in corners {
            g.setFillColor(CGColor(srgbRed: c.0, green: c.1, blue: c.2, alpha: 1))
            g.fill(CGRect(x: o.x, y: o.y, width: arm * sx, height: thick * sy).standardized)
            g.fill(CGRect(x: o.x, y: o.y, width: thick * sx, height: arm * sy).standardized)
        }

        // what the processor should be told
        let label = "LED wall \(wall.w) × \(wall.h) px at \(wall.x), \(wall.y)"
        let sub = "panels \(panelPx) px · \(Int((Double(wall.w) / Double(max(1, panelPx))).rounded(.up))) × \(Int((Double(wall.h) / Double(max(1, panelPx))).rounded(.up)))"
        let ts = max(10 * k, min(h * 0.07, w * 0.04))
        g.setFillColor(CGColor(gray: 0, alpha: 0.75))
        g.fill(CGRect(x: w * 0.15, y: h * 0.12, width: w * 0.7, height: ts * 2.6))
        text(g, label, at: CGPoint(x: w / 2, y: h * 0.12 + ts * 0.85), size: ts, gray: 1, centred: true)
        text(g, sub, at: CGPoint(x: w / 2, y: h * 0.12 + ts * 1.95), size: ts * 0.6, gray: 0.8, centred: true)
        return g.makeImage()
    }

    private static func text(_ g: CGContext, _ s: String, at p: CGPoint, size: CGFloat, gray: CGFloat, centred: Bool) {
        let font = CTFontCreateWithName("Menlo-Bold" as CFString, size, nil)
        let attr = NSAttributedString(string: s, attributes: [
            NSAttributedString.Key(kCTFontAttributeName as String): font,
            NSAttributedString.Key(kCTForegroundColorAttributeName as String): CGColor(gray: gray, alpha: 1),
        ])
        let line = CTLineCreateWithAttributedString(attr)
        let b = CTLineGetBoundsWithOptions(line, .useGlyphPathBounds)
        g.saveGState()
        g.textMatrix = CGAffineTransform(scaleX: 1, y: -1)
        // centred: on the point; else hanging from it (the top left of a panel)
        g.textPosition = centred ? CGPoint(x: p.x - b.midX, y: p.y + b.midY) : CGPoint(x: p.x - b.minX, y: p.y + b.maxY)
        CTLineDraw(line, g)
        g.restoreGState()
    }
}
