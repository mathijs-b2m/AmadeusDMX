// swift-tools-version: 6.2
// Decisive Lightning for macOS: a native app on top of the Python engine (side by side with the web UI).
//
//  DecisiveKit         the shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
//  DecisiveLightning   the app: SwiftUI + Metal
import PackageDescription

let package = Package(
    name: "DecisiveLightning",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "DecisiveKit", targets: ["DecisiveKit"]),
        .executable(name: "DecisiveLightning", targets: ["DecisiveLightning"]),
        .executable(name: "DecisiveLink", targets: ["DecisiveLink"]),
    ],
    targets: [
        .target(name: "DecisiveKit", swiftSettings: [.swiftLanguageMode(.v5)]),
        .executableTarget(name: "DecisiveLightning", dependencies: ["DecisiveKit"],
                          swiftSettings: [.swiftLanguageMode(.v5)]),
        // the DJ laptop's companion: passes VirtualDJ's mix state to the lighting computer (decisive/link.py)
        .executableTarget(name: "DecisiveLink", swiftSettings: [.swiftLanguageMode(.v5)]),
    ]
)
