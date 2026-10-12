// swift-tools-version: 6.2
// Amadeus DMX for macOS: a native app on top of the Python engine (side by side with the web UI).
//
//  AmadeusKit   the shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
//  AmadeusDMX   the app: SwiftUI + Metal
import PackageDescription

let package = Package(
    name: "AmadeusDMX",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "AmadeusKit", targets: ["AmadeusKit"]),
        .executable(name: "AmadeusDMX", targets: ["AmadeusDMX"]),
        .executable(name: "AmadeusLink", targets: ["AmadeusLink"]),
    ],
    targets: [
        .target(name: "AmadeusKit", swiftSettings: [.swiftLanguageMode(.v5)]),
        .executableTarget(name: "AmadeusDMX", dependencies: ["AmadeusKit"],
                          swiftSettings: [.swiftLanguageMode(.v5)]),
        // the DJ laptop's companion: passes VirtualDJ's mix state to the lighting computer (amadeus/link.py)
        .executableTarget(name: "AmadeusLink", swiftSettings: [.swiftLanguageMode(.v5)]),
    ]
)
