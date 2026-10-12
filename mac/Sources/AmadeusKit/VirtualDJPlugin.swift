// The AmadeusLink plugin for VirtualDJ (vdj/): where VirtualDJ looks for it, whether ours is there, putting it
// there. Amadeus DMX installs it from the engine folder; Amadeus Link carries its own copy (a DJ laptop has no
// engine). Both copies are the same build (vdj/build.sh), so "up to date" is the same bytes.
import Foundation

public enum VirtualDJPlugin {
    public enum Status: Sendable { case notInstalled, upToDate, outdated }

    /// Where VirtualDJ (Apple Silicon) loads sound effects from.
    public static var installed: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "Library/Application Support/VirtualDJ/PluginsMacArm/SoundEffect/AmadeusLink.bundle")
    }

    /// The installed plugin against the one this app would install.
    public static func status(comparedTo bundled: URL?) -> Status {
        guard FileManager.default.fileExists(atPath: installed.path) else { return .notInstalled }
        guard let bundled, let ours = try? Data(contentsOf: executable(bundled)) else { return .upToDate }
        return (try? Data(contentsOf: executable(installed))) == ours ? .upToDate : .outdated
    }

    /// Copies the plugin into VirtualDJ's folder (replacing an older one). VirtualDJ loads it at its next start.
    public static func install(from bundled: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: installed.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? fm.removeItem(at: installed)
        try fm.copyItem(at: bundled, to: installed)
    }

    private static func executable(_ bundle: URL) -> URL { bundle.appending(path: "Contents/MacOS/AmadeusLink") }
}
