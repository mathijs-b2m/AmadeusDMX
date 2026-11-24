// The LED Wall Output: the wall's picture (WallSource) on a real LED wall. Like Resolume's Advanced Output or a
// media server's: a borderless window filling a display (the HDMI into the LED processor), the picture in the
// wall's rectangle of that display, pixel for pixel, black around it. Or in a window, to try it without a second
// display or to capture it (OBS).
//
// It draws on its own display link, at that display's refresh rate, so it plays while no 3D stage is open. It never
// covers the display the app is on (QLC+ users lose their controls that way), goes black when the show stops
// (never a frozen picture), keeps that display awake, and comes back by itself when the display is plugged in again.
import AmadeusKit
import AppKit
import IOKit.pwr_mgt
import Metal
import MetalKit
import Observation
import QuartzCore

/// A display the output can go to.
struct OutputScreen: Identifiable, Equatable {
    var id: String          // its UUID
    var name: String
    var pixels: (w: Int, h: Int)   // what it sends: the display mode's pixels
    var refresh: Double
    /// A HiDPI ("looks like") mode: drawn at twice the pixels and scaled, so pixels don't land one to one.
    var hiDPI: Bool
    var holdsApp: Bool      // the app's main window is on it
    static func == (a: Self, b: Self) -> Bool {
        a.id == b.id && a.name == b.name && a.pixels == b.pixels && a.refresh == b.refresh && a.hiDPI == b.hiDPI && a.holdsApp == b.holdsApp
    }
    var label: String { "\(name) · \(pixels.w) × \(pixels.h)" + (refresh > 0 ? " · \(Int(refresh.rounded())) Hz" : "") }
}

@MainActor
@Observable
final class WallOutputController {
    var settings = WallOutputSettings.load() {
        didSet {
            guard settings != oldValue else { return }
            settings.save()
            apply()
            if settings.on != oldValue.on { onToggle?(settings.on) }
        }
    }
    private(set) var screens: [OutputScreen] = []
    /// What the output is doing, for the window: nil while all is well.
    private(set) var problem: String?
    /// Where it plays right now ("Display 2 · 1920 × 1080"), nil while it doesn't.
    private(set) var playingOn: String?
    /// The pixels of what it plays on right now (the display's, or the window's).
    private(set) var outputPixels: (w: Int, h: Int)?

    /// The show: its hello, its newest frame, and whether frames still arrive.
    @ObservationIgnored var source: () -> (Hello?, Frame?, Bool) = { (nil, nil, false) }
    /// The output was switched on or off (the feed must carry full frames while it is on).
    @ObservationIgnored var onToggle: ((Bool) -> Void)?

    @ObservationIgnored private var window: NSWindow?
    @ObservationIgnored private var view: WallOutputView?
    @ObservationIgnored private var placed: (screen: String?, frame: NSRect)?
    @ObservationIgnored private var sleepAssertion: IOPMAssertionID = 0
    @ObservationIgnored private var observers: [NSObjectProtocol] = []

    init() {
        let nc = NotificationCenter.default
        observers.append(nc.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refreshScreens(); self?.apply() }
        })
        // the app's window moved to another display: what it may cover changed
        observers.append(nc.addObserver(forName: NSWindow.didChangeScreenNotification, object: nil, queue: .main) { [weak self] n in
            MainActor.assumeIsolated {
                guard let self, (n.object as? NSWindow) !== self.window else { return }
                self.refreshScreens(); self.apply()
            }
        })
        // after launch: the app (NSApp) and its main window are up, which display it is on is known
        DispatchQueue.main.async { self.refreshScreens(); self.apply() }
    }

    // MARK: displays

    func refreshScreens() {
        let app = Self.appWindow?.screen
        let list = NSScreen.screens.compactMap { s -> OutputScreen? in
            guard let id = Self.displayID(s), let uuid = Self.uuid(id) else { return nil }
            let mode = CGDisplayCopyDisplayMode(id)
            let pw = mode?.pixelWidth ?? Int(s.frame.width * s.backingScaleFactor)
            let ph = mode?.pixelHeight ?? Int(s.frame.height * s.backingScaleFactor)
            return OutputScreen(id: uuid, name: s.localizedName, pixels: (pw, ph), refresh: mode?.refreshRate ?? 0,
                                hiDPI: (mode.map { $0.pixelWidth != $0.width } ?? false), holdsApp: s == app)
        }
        if list != screens { screens = list }
    }

    var chosenScreen: OutputScreen? { screens.first { $0.id == settings.display } }

    /// The display to offer first: one the app is not on.
    var suggestedScreen: OutputScreen? { screens.first { !$0.holdsApp } }

    static var appWindow: NSWindow? {
        guard let app = NSApp else { return nil }
        return app.windows.first { $0.identifier?.rawValue.hasPrefix("main") ?? false && $0.isVisible }
            ?? app.mainWindow ?? app.windows.first { $0.isVisible && $0.canBecomeMain && !($0 is WallOutputWindow) }
    }

    private static func displayID(_ s: NSScreen) -> CGDirectDisplayID? {
        (s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber).map { CGDirectDisplayID($0.uint32Value) }
    }

    private static func uuid(_ id: CGDirectDisplayID) -> String? {
        guard let u = CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue() else { return nil }
        return CFUUIDCreateString(nil, u) as String?
    }

    private func nsScreen(_ uuid: String) -> NSScreen? {
        NSScreen.screens.first { Self.displayID($0).flatMap(Self.uuid) == uuid }
    }

    // MARK: on and off

    /// Opens, moves or closes the output for the settings and the displays connected now.
    func apply() {
        WallSource.shared.lead = settings.leadMs / 1000
        guard settings.on else { close(); problem = nil; WallSource.shared.scale = 1; return }
        switch settings.target {
        case .window:
            problem = nil
            open(on: nil)
        case .display:
            guard let id = settings.display else { close(); problem = "Choose the display that goes to the LED wall."; return }
            guard let info = chosenScreen, let screen = nsScreen(id) else {
                close()
                problem = "\(settings.displayName ?? "The display") isn't connected. The output starts by itself when it is."
                return
            }
            if info.holdsApp {
                close()
                problem = "Amadeus DMX is on \(info.name). Move the app's window to another display, or choose another display: the output would cover it."
                return
            }
            problem = info.hiDPI ? "\(info.name) runs a scaled (HiDPI) resolution: the wall's pixels won't land one to one. Choose a native resolution in System Settings › Displays." : nil
            open(on: screen)
        }
        let px = outputPixels.map { WallOutputLayout.wallRect(settings.target == .display ? settings.rect : nil, display: $0.w, $0.h) }
        WallSource.shared.scale = WallOutputLayout.pictureScale(forWallHeight: px.map { WallOutputLayout.fit($0).h })
    }

    private func open(on screen: NSScreen?) {
        let frame = screen?.frame ?? NSRect(x: 0, y: 0, width: 960, height: 540)
        let key = screen.flatMap { Self.displayID($0).flatMap(Self.uuid) }
        // already there (the same display, or still the window): only follow a display's new size
        if let window, placed?.screen == key, window.styleMask.contains(.titled) == (screen == nil) {
            if screen != nil, placed?.frame != frame { window.setFrame(frame, display: true); placed = (key, frame) }
            updatePixels()
            return
        }
        close()
        let w: NSWindow
        if let screen {
            w = WallOutputWindow(contentRect: frame, styleMask: .borderless, backing: .buffered, defer: false, screen: screen)
            w.level = .screenSaver   // over the menu bar and the Dock of that display
            w.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle, .fullScreenAuxiliary]
            w.ignoresMouseEvents = true
            w.hasShadow = false
            w.setFrame(frame, display: false)
        } else {
            w = WallOutputWindow(contentRect: frame, styleMask: [.titled, .closable, .resizable, .miniaturizable],
                                 backing: .buffered, defer: false)
            w.title = "LED Wall"
            w.setFrameAutosaveName("LEDWallOutputWindow")
            w.contentAspectRatio = NSSize(width: 16, height: 9)
            w.delegate = closeWatcher
        }
        w.isReleasedWhenClosed = false
        w.isOpaque = true
        w.backgroundColor = .black
        w.animationBehavior = .none
        let v = WallOutputView(frame: NSRect(origin: .zero, size: frame.size), controller: self)
        w.contentView = v
        window = w
        view = v
        placed = (key, frame)
        if screen == nil { w.makeKeyAndOrderFront(nil) } else { w.orderFrontRegardless() }
        v.start()
        updatePixels()
        keepAwake(true)
        playingOn = screen.map { s in screens.first { $0.id == key }?.label ?? s.localizedName } ?? "a window"
    }

    func close() {
        view?.stop()
        window?.delegate = nil
        window?.orderOut(nil)
        window?.close()
        window = nil
        view = nil
        placed = nil
        playingOn = nil
        outputPixels = nil
        keepAwake(false)
    }

    /// The preview window closed by its own button: the output is off.
    @ObservationIgnored private lazy var closeWatcher = CloseWatcher { [weak self] in
        guard let self else { return }
        self.view?.stop()
        self.window = nil; self.view = nil
        self.settings.on = false
    }

    fileprivate func updatePixels() {
        guard let view else { return }
        let d = view.drawablePixels
        let mode = settings.target == .display ? chosenScreen?.pixels : nil
        let px = mode ?? d
        if outputPixels.map({ $0 != px }) ?? true { outputPixels = px }
    }

    /// The display must not sleep while the wall plays (the idle timer would black out the LED wall mid-show).
    private func keepAwake(_ on: Bool) {
        if on, sleepAssertion == 0 {
            IOPMAssertionCreateWithName(kIOPMAssertionTypePreventUserIdleDisplaySleep as CFString,
                                        IOPMAssertionLevel(kIOPMAssertionLevelOn), "The LED wall output is playing" as CFString,
                                        &sleepAssertion)
        } else if !on, sleepAssertion != 0 {
            IOPMAssertionRelease(sleepAssertion)
            sleepAssertion = 0
        }
    }

    // MARK: drawing

    /// The wall's rectangle in the drawable's pixels, and where the picture goes inside it.
    fileprivate func layout(drawable d: (w: Int, h: Int)) -> (wall: PixelRect, picture: PixelRect) {
        guard settings.target == .display, let mode = chosenScreen?.pixels else {
            let all = PixelRect(x: 0, y: 0, w: d.w, h: d.h)
            return (all, WallOutputLayout.fit(all))
        }
        let wall = WallOutputLayout.scaled(WallOutputLayout.wallRect(settings.rect, display: mode.w, mode.h), from: mode, to: d)
        return (wall, WallOutputLayout.fit(wall))
    }

    /// The test card's picture for this wall (kept until the wall's size or the panel size changes).
    @ObservationIgnored private var card: (key: String, texture: MTLTexture)?
    fileprivate func testCard(_ wall: PixelRect, modeWall: PixelRect) -> MTLTexture? {
        let key = "\(wall.w)x\(wall.h):\(modeWall.x),\(modeWall.y),\(modeWall.w),\(modeWall.h):\(settings.panelPx)"
        if let card, card.key == key { return card.texture }
        guard let gpu = WallSource.gpu, let img = TestCard.draw(pixels: (wall.w, wall.h), wall: modeWall, panelPx: settings.panelPx),
              let t = try? MTKTextureLoader(device: gpu.device).newTexture(cgImage: img, options: [.SRGB: false]) else { return nil }
        card = (key, t)
        return t
    }

    /// The wall's rectangle in the display's own pixels (what the processor is told), for the test card's labels.
    fileprivate var modeWall: PixelRect {
        let px = chosenScreen?.pixels ?? outputPixels ?? (1920, 1080)
        return WallOutputLayout.wallRect(settings.target == .display ? settings.rect : nil, display: px.w, px.h)
    }
}

final class WallOutputWindow: NSWindow {
    override var canBecomeKey: Bool { styleMask.contains(.titled) }
    override var canBecomeMain: Bool { false }
}

private final class CloseWatcher: NSObject, NSWindowDelegate {
    let closed: @MainActor () -> Void
    init(_ closed: @escaping @MainActor () -> Void) { self.closed = closed }
    func windowWillClose(_ n: Notification) { MainActor.assumeIsolated { closed() } }
}

/// Draws one picture of the output: black, and in it the wall's picture (fitted into the wall's rectangle) or the
/// test card (the whole rectangle). The output's view and the stage snapshot (development) draw with it.
@MainActor
final class WallOutputDrawer {
    private let pipe: MTLRenderPipelineState?

    init() {
        guard let gpu = WallSource.gpu else { pipe = nil; return }
        do {
            let lib = try gpu.device.makeLibrary(source: WallShaders.source, options: nil)
            let d = MTLRenderPipelineDescriptor()
            d.vertexFunction = lib.makeFunction(name: "wall_fs_vertex")
            d.fragmentFunction = lib.makeFunction(name: "wall_output")
            d.colorAttachments[0].pixelFormat = .bgra8Unorm
            pipe = try gpu.device.makeRenderPipelineState(descriptor: d)
        } catch { print("wall output shaders: \(error)"); pipe = nil }
    }

    /// `level`: the brightness ceiling times the fade to black; `card`: the test card, else the show's picture.
    func encode(_ cmd: MTLCommandBuffer, into target: MTLTexture, wall: PixelRect, picture: PixelRect, level: Float,
                card: MTLTexture?, time: Float) {
        let rp = MTLRenderPassDescriptor()
        rp.colorAttachments[0].texture = target
        rp.colorAttachments[0].loadAction = .clear
        rp.colorAttachments[0].clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        rp.colorAttachments[0].storeAction = .store
        guard let pipe, let enc = cmd.makeRenderCommandEncoder(descriptor: rp) else { return }
        let texture = card ?? (level > 0 ? WallSource.shared.picture : nil)
        if let texture {
            let r = card != nil ? wall : picture
            var p = SIMD4<Float>(level, time, card != nil ? 1 : 0, 0)
            enc.setRenderPipelineState(pipe)
            enc.setViewport(MTLViewport(originX: Double(r.x), originY: Double(r.y), width: Double(r.w), height: Double(r.h),
                                        znear: 0, zfar: 1))
            enc.setFragmentTexture(texture, index: 0)
            enc.setFragmentBytes(&p, length: MemoryLayout<SIMD4<Float>>.stride, index: 0)
            enc.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
        }
        enc.endEncoding()
    }
}

/// The output's view: a Metal layer drawn on the display link of the display it is on.
@MainActor
final class WallOutputView: NSView {
    private weak var controller: WallOutputController?
    private let metal = CAMetalLayer()
    private var link: CADisplayLink?
    private let drawer = WallOutputDrawer()
    private var fade: Float = 0
    private var last = CACurrentMediaTime()
    private let start0 = CACurrentMediaTime()

    init(frame: NSRect, controller: WallOutputController) {
        self.controller = controller
        super.init(frame: frame)
        wantsLayer = true
        metal.device = WallSource.gpu?.device
        metal.pixelFormat = .bgra8Unorm
        metal.framebufferOnly = true
        metal.colorspace = CGColorSpace(name: CGColorSpace.sRGB)
        metal.displaySyncEnabled = true
        metal.maximumDrawableCount = 3
        metal.isOpaque = true
        metal.backgroundColor = CGColor(gray: 0, alpha: 1)
    }

    required init?(coder: NSCoder) { fatalError() }

    override func makeBackingLayer() -> CALayer { metal }

    var drawablePixels: (w: Int, h: Int) { (Int(metal.drawableSize.width), Int(metal.drawableSize.height)) }

    override func layout() {
        super.layout()
        resize()
    }

    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        resize()
    }

    private func resize() {
        let k = window?.backingScaleFactor ?? 1
        metal.contentsScale = k
        let size = CGSize(width: max(1, (bounds.width * k).rounded()), height: max(1, (bounds.height * k).rounded()))
        if metal.drawableSize != size { metal.drawableSize = size; controller?.updatePixels() }
    }

    func start() {
        guard link == nil else { return }
        resize()
        let l = displayLink(target: self, selector: #selector(step))
        l.add(to: .main, forMode: .common)
        link = l
    }

    func stop() {
        link?.invalidate()
        link = nil
    }

    @objc private func step(_ l: CADisplayLink) {
        guard let controller, let gpu = WallSource.gpu else { return }
        let now = CACurrentMediaTime()
        let dt = Float(min(0.1, now - last))
        last = now
        guard let drawable = metal.nextDrawable(), let cmd = gpu.queue.makeCommandBuffer() else { return }
        let s = controller.settings
        let (hello, frame, receiving) = controller.source()
        let state = WallSource.shared.prepare(frame: frame, hello: hello, now: now, cmd: cmd)
        // the show stopped (or this rig has no LED wall): black within half a second, never a frozen picture
        let live: Float = receiving && state != nil ? 1 : 0
        fade += (live - fade) * min(1, dt * (live > fade ? 6 : 4))
        if live == 0 && fade < 0.01 { fade = 0 }

        let (wall, pic) = controller.layout(drawable: drawablePixels)
        let card = s.testPattern ? controller.testCard(wall, modeWall: controller.modeWall) : nil
        drawer.encode(cmd, into: drawable.texture, wall: wall, picture: pic, level: Float(s.brightness) * (card != nil ? 1 : fade),
                      card: card, time: Float(now - start0))
        cmd.present(drawable)
        cmd.commit()
    }
}
