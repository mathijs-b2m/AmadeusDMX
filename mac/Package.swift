// swift-tools-version: 6.2
// Amadeus DMX for macOS: a native app on top of the Python engine (side by side with the web UI).
//
//  AmadeusKit   the shared library: protocol, live feed, engine supervisor, setup API, sets, palettes
//  AmadeusDMX   the app: SwiftUI + Metal
//  Both apps update with Sparkle (release builds, see README › Updates; AmadeusKit/Updates.swift)
import PackageDescription

let package = Package(
    name: "AmadeusDMX",
    platforms: [.macOS(.v26)],
    products: [
        .library(name: "AmadeusKit", targets: ["AmadeusKit"]),
        .executable(name: "AmadeusDMX", targets: ["AmadeusDMX"]),
        .executable(name: "AmadeusLink", targets: ["AmadeusLink"]),
    ],
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.7.0"),
    ],
    targets: [
        .target(name: "AmadeusKit", dependencies: [.product(name: "Sparkle", package: "Sparkle")], swiftSettings: [.swiftLanguageMode(.v5)]),
        .executableTarget(name: "AmadeusDMX", dependencies: ["AmadeusKit"],
                          swiftSettings: [.swiftLanguageMode(.v5)]),
        // the DJ laptop's companion: passes VirtualDJ's mix state to the lighting computer (amadeus/link.py)
        .executableTarget(name: "AmadeusLink", dependencies: ["AmadeusKit"], swiftSettings: [.swiftLanguageMode(.v5)]),
        // what Amadeus Link reads from djay Pro and Mixxx, checked against the engine's own readers (swift test)
        .testTarget(name: "AmadeusLinkTests", dependencies: ["AmadeusLink"], swiftSettings: [.swiftLanguageMode(.v5)]),
    ]
)
