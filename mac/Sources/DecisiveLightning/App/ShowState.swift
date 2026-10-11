// The app's pages, the show's state, and what a show does with the computer (the mode).
import AppKit
import DecisiveKit
import Foundation
import Observation
import Security

enum Section: String, CaseIterable, Identifiable, Hashable {
    case show, set, rig, engine
    var id: String { rawValue }
    var title: String {
        switch self {
        case .show: "Show"
        case .rig: "Rigs"
        case .set: "Sets"
        case .engine: "Engine"
        }
    }
    var symbol: String {
        switch self {
        case .show: "sparkles.tv"
        case .rig: "square.split.bottomrightquarter"
        case .set: "light.overhead.right"
        case .engine: "terminal"
        }
    }
    /// What the page is for, in a few words (the sidebar's tooltip).
    var help: String {
        switch self {
        case .show: "The show: the stage, the music and the director"
        case .rig: "Your rigs (the venues: trusses, stage, zones), and the sets placed on them"
        case .set: "Your sets of fixtures: their DMX patch and where the DMX goes"
        case .engine: "The engine's log"
        }
    }
}

/// What the show engine is doing, as the user sees it.
enum ShowState: Equatable {
    case stopped
    case starting
    case waitingForDJ        // running, VirtualDJ not sending (yet)
    case live                // lights follow the mix
    case playing             // a track played by the engine itself
    case attached            // an engine started elsewhere (terminal) is sending: we only watch
    case failed(String)

    var title: String {
        switch self {
        case .stopped: "Stopped"
        case .starting: "Starting…"
        case .waitingForDJ: "Waiting for VirtualDJ"
        case .live: "Live"
        case .playing: "Playing"
        case .attached: "Watching"
        case .failed: "Engine Stopped"
        }
    }

    var symbol: String {
        switch self {
        case .stopped: "stop.circle"
        case .starting: "hourglass"
        case .waitingForDJ: "dot.radiowaves.left.and.right"
        case .live: "waveform"
        case .playing: "play.circle"
        case .attached: "eye"
        case .failed: "exclamationmark.triangle"
        }
    }

    var isActive: Bool { self == .live || self == .playing || self == .attached }
}

/// What a show does with the computer: draw the stage, drive the lights, or both.
enum ShowMode: String, CaseIterable, Identifiable {
    case visualise, perform, both
    var id: String { rawValue }
    var title: String {
        switch self {
        case .visualise: "Visualise Only"
        case .perform: "Perform Only"
        case .both: "Perform + Visualise"
        }
    }
    var symbol: String {
        switch self {
        case .visualise: "cube.transparent"
        case .perform: "light.beacon.max"
        case .both: "square.stack.3d.up"
        }
    }
    var detail: String {
        switch self {
        case .visualise: "The 3D stage only: nothing goes to the lights."
        case .perform: "The lights only: no 3D stage, the computer's power goes to the show."
        case .both: "The lights, and the 3D stage alongside."
        }
    }
    var sendsDMX: Bool { self != .visualise }
    var renders3D: Bool { self != .perform }
}
