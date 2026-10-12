// SwiftUI ↔ Metal: the stage view with trackpad/mouse camera control.
//   drag: orbit · ⌥-drag or two-finger drag with ⌘: pan · scroll / pinch: zoom · double-click: back to the preset
import AppKit
import AmadeusKit
import MetalKit
import SwiftUI

/// The rig editor: gets first go at clicks, drags and keys on the stage.
@MainActor
protocol StageEditing: AnyObject {
    /// A click: true if it grabbed something (then drags move it instead of the camera). `extend`: ⇧ held.
    func pick(origin: SIMD3<Float>, dir: SIMD3<Float>, extend: Bool) -> Bool
    func drag(origin: SIMD3<Float>, dir: SIMD3<Float>, free: Bool)
    func endDrag()
    func clickedEmpty()
    func key(_ e: NSEvent) -> Bool
    /// Something dragged in from elsewhere (text, e.g. fixture ids) is over / dropped on the stage.
    func dropHover(origin: SIMD3<Float>, dir: SIMD3<Float>)
    func drop(_ payload: String, origin: SIMD3<Float>, dir: SIMD3<Float>) -> Bool
    func dropEnded()
    /// The pointer moved over the stage (no button down).
    func hover(origin: SIMD3<Float>, dir: SIMD3<Float>)
}

extension StageEditing {
    func dropHover(origin: SIMD3<Float>, dir: SIMD3<Float>) {}
    func drop(_ payload: String, origin: SIMD3<Float>, dir: SIMD3<Float>) -> Bool { false }
    func dropEnded() {}
    func hover(origin: SIMD3<Float>, dir: SIMD3<Float>) {}
}

final class StageMTKView: MTKView {
    weak var renderer: StageRenderer?
    weak var editor: StageEditing?
    private var last: NSPoint = .zero
    private var dragging = false

    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    // don't draw while minimised (occlusion state is unreliable with Stage Manager: it paused visible windows)
    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        guard let w = window else { return }
        for (name, paused) in [(NSWindow.didMiniaturizeNotification, true), (NSWindow.didDeminiaturizeNotification, false)] {
            NotificationCenter.default.addObserver(forName: name, object: w, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated { self?.isPaused = paused }
            }
        }
        // nor while the app is hidden (⌘H): nobody sees it, the lights don't need it
        for (name, paused) in [(NSApplication.didHideNotification, true), (NSApplication.didUnhideNotification, false)] {
            NotificationCenter.default.addObserver(forName: name, object: nil, queue: .main) { [weak self] _ in
                MainActor.assumeIsolated {
                    guard let self else { return }
                    self.isPaused = paused || (self.window?.isMiniaturized ?? false)
                    if !paused { self.renderer?.wake() }
                }
            }
        }
        isPaused = false
        registerForDraggedTypes([.string])
    }

    private func ray(_ e: NSEvent) -> (SIMD3<Float>, SIMD3<Float>)? { ray(windowPoint: e.locationInWindow) }

    private func ray(windowPoint: NSPoint) -> (SIMD3<Float>, SIMD3<Float>)? {
        guard let r = renderer else { return nil }
        let p = convert(windowPoint, from: nil)
        let ray = r.ray(at: p, in: bounds.size)
        return (ray.origin, ray.dir)
    }

    // fixtures dragged in from the inspector
    override func draggingEntered(_ info: NSDraggingInfo) -> NSDragOperation { draggingUpdated(info) }

    override func draggingUpdated(_ info: NSDraggingInfo) -> NSDragOperation {
        guard let editor, let (o, d) = ray(windowPoint: info.draggingLocation) else { return [] }
        editor.dropHover(origin: o, dir: d)
        return .move
    }

    override func draggingExited(_ info: NSDraggingInfo?) { editor?.dropEnded() }

    override func performDragOperation(_ info: NSDraggingInfo) -> Bool {
        guard let editor, let text = info.draggingPasteboard.string(forType: .string),
              let (o, d) = ray(windowPoint: info.draggingLocation) else { return false }
        return editor.drop(text, origin: o, dir: d)
    }

    override func mouseMoved(with e: NSEvent) {
        renderer?.wake()
        if let editor, let (o, d) = ray(e) { editor.hover(origin: o, dir: d) }
        super.mouseMoved(with: e)
    }

    override func updateTrackingAreas() {  // mouse-moved events (the editor lights what a click would pick)
        super.updateTrackingAreas()
        trackingAreas.forEach(removeTrackingArea)
        addTrackingArea(NSTrackingArea(rect: .zero, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect], owner: self))
    }

    override func mouseDown(with e: NSEvent) {
        renderer?.wake()
        last = e.locationInWindow
        window?.makeFirstResponder(self)
        if let editor, let (o, d) = ray(e) {
            if editor.pick(origin: o, dir: d, extend: e.modifierFlags.contains(.shift)) { dragging = true; return }
            if e.clickCount == 1 { editor.clickedEmpty() }
        }
        if e.clickCount == 2, let r = renderer { r.setPreset(r.preset) }
    }

    override func mouseUp(with e: NSEvent) {
        if dragging { editor?.endDrag(); dragging = false }
    }

    override func keyDown(with e: NSEvent) {
        if editor?.key(e) == true { return }
        super.keyDown(with: e)
    }

    override func mouseDragged(with e: NSEvent) {
        if dragging, let (o, d) = ray(e) {
            editor?.drag(origin: o, dir: d, free: e.modifierFlags.contains(.option))
            return
        }
        let p = e.locationInWindow, dx = Float(p.x - last.x), dy = Float(p.y - last.y)
        last = p
        if e.modifierFlags.contains(.option) || e.modifierFlags.contains(.command) {
            renderer?.pan(dx: dx, dy: dy)
        } else {
            renderer?.orbit(dx: dx, dy: dy)
        }
    }

    override func rightMouseDown(with e: NSEvent) { last = e.locationInWindow }
    override func rightMouseDragged(with e: NSEvent) {
        let p = e.locationInWindow
        renderer?.pan(dx: Float(p.x - last.x), dy: Float(p.y - last.y))
        last = p
    }

    override func scrollWheel(with e: NSEvent) {
        if e.hasPreciseScrollingDeltas {  // trackpad: two-finger scroll orbits, like turning a model
            renderer?.orbit(dx: Float(-e.scrollingDeltaX) * 1.5, dy: Float(-e.scrollingDeltaY) * 1.5)
        } else {
            renderer?.zoom(1 - Float(e.scrollingDeltaY) * 0.04)
        }
    }

    override func magnify(with e: NSEvent) {
        renderer?.zoom(1 - Float(e.magnification))
    }
}

/// Owns the renderer for a view's lifetime and lets SwiftUI talk to it.
@MainActor
final class StageController: ObservableObject {
    fileprivate(set) var renderer: StageRenderer?
    @Published var preset: CameraPreset = UserDefaults.standard.string(forKey: "camera").flatMap(CameraPreset.init(rawValue:))
        ?? .frontOfHouse {   // -camera Plan / Drone … (development)
        didSet { renderer?.setPreset(preset) }
    }
    @Published var haze: Double = 0.6 { didSet { renderer?.haze = Float(haze) } }
    @Published var exposure: Double = 1.0 { didSet { renderer?.exposure = Float(exposure) } }
    @Published var autoOrbit = false { didSet { renderer?.autoOrbit = autoOrbit } }
    var workLight: Float = 0 { didSet { renderer?.workLight = workLight } }
    @Published var wallScene: WallScene = .auto { didSet { renderer?.wallScene = wallScene } }

    var input: (() -> (StageInput?, Frame?))? {
        didSet { renderer?.input = input }
    }
    var highlight: Set<String> = [] { didSet { renderer?.highlight = highlight } }
    weak var editor: StageEditing? { didSet { view?.editor = editor } }
    fileprivate weak var view: StageMTKView?

    func setPreset(_ p: CameraPreset) { preset = p }

    fileprivate func attach(_ r: StageRenderer) {
        renderer = r
        r.input = input
        r.highlight = highlight
        r.haze = Float(haze)
        r.exposure = Float(exposure)
        r.autoOrbit = autoOrbit
        r.workLight = workLight
        r.wallScene = wallScene
        r.setPreset(preset, animated: false)
    }
}

struct StageView: NSViewRepresentable {
    @ObservedObject var controller: StageController

    func makeNSView(context: Context) -> StageMTKView {
        let v = StageMTKView(frame: .zero)
        if let r = StageRenderer(view: v) {
            v.renderer = r
            v.editor = controller.editor
            controller.view = v
            controller.attach(r)
            context.coordinator.renderer = r
            context.coordinator.controller = controller
        }
        return v
    }

    func updateNSView(_ v: StageMTKView, context: Context) {}

    static func dismantleNSView(_ v: StageMTKView, coordinator: Coordinator) {
        v.isPaused = true
        v.renderer = nil
        if let c = coordinator.controller, c.renderer === coordinator.renderer { c.renderer = nil }
        coordinator.renderer = nil
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    final class Coordinator {
        var renderer: StageRenderer?   // keeps the renderer (the view's delegate is weak)
        weak var controller: StageController?
    }
}
