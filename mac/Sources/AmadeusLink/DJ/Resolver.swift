// Which file on this laptop a DJ software's track is (as amadeus/show/sources/resolve.py): the path as given,
// then a file of that name, then a file whose name holds the title and the artist, its length deciding between
// look-alikes. Looks in ~/Music and in the folders the DJ software's library knows.
import AVFoundation
import Foundation

final class Resolver: @unchecked Sendable {
    static let audio: Set<String> = ["mp3", "wav", "flac", "aiff", "aif", "m4a", "aac", "ogg", "opus", "alac"]
    static let lengthTolerance = 2.5

    private let lock = NSLock()
    private var folders: [URL] = []
    private var files: [URL] = []
    private var byName: [String: [URL]] = [:]
    private var memo: [String: String] = [:]
    private let q = DispatchQueue(label: "amadeus.link.resolver", qos: .utility)

    init(folders: [URL] = [FileManager.default.homeDirectoryForCurrentUser.appending(path: "Music")]) {
        add(folders)
    }

    /// More places to look (where the DJ software's known tracks are), indexed in the background.
    func add(_ more: [URL]) {
        lock.lock()
        var new: [URL] = []
        for f in Set(more.map(\.standardizedFileURL)) where !(folders + new).contains(where: { f.path.hasPrefix($0.path + "/") || f == $0 }) {
            new = new.filter { !$0.path.hasPrefix(f.path + "/") } + [f]
        }
        folders += new
        lock.unlock()
        guard !new.isEmpty else { return }
        q.async { [weak self] in self?.index(new) }
    }

    private func index(_ roots: [URL]) {
        var found: [URL] = []
        let fm = FileManager.default
        for root in roots {
            let e = fm.enumerator(at: root, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles, .skipsPackageDescendants])
            while let f = e?.nextObject() as? URL {
                if Self.audio.contains(f.pathExtension.lowercased()) { found.append(f) }
            }
        }
        lock.lock()
        files += found
        for f in found { byName[f.lastPathComponent.lowercased(), default: []].append(f) }
        memo = memo.filter { !$0.value.isEmpty }  // what wasn't found may be there now
        lock.unlock()
    }

    /// The local file, or "" (unknown, or not indexed yet).
    func find(path: String = "", artist: String = "", title: String = "", length: Double = 0) -> String {
        let key = "\(path)|\(artist)|\(title)|\(Int(length.rounded()))"
        lock.lock()
        if let hit = memo[key] { lock.unlock(); return hit }
        lock.unlock()
        if !path.isEmpty, FileManager.default.fileExists(atPath: path) { return remember(key, path) }
        lock.lock()
        let (names, all) = (byName, files)
        lock.unlock()
        let name = path.isEmpty ? "" : (path.replacingOccurrences(of: "\\", with: "/") as NSString).lastPathComponent.lowercased()
        if let same = names[name], !same.isEmpty { return remember(key, closest(same, length).path) }
        let wantTitle = Set(Self.words(title)), wantArtist = Set(Self.words(artist))
        guard !wantTitle.isEmpty else { return remember(key, "") }
        let hits: [(Int, URL)] = all.compactMap { f in
            let have = Set(Self.words(f.deletingPathExtension().lastPathComponent) + Self.words(f.deletingLastPathComponent().lastPathComponent))
            return wantTitle.isSubset(of: have) ? (wantArtist.intersection(have).count, f) : nil
        }
        guard let best = hits.map(\.0).max() else { return remember(key, "") }
        return remember(key, closest(hits.filter { $0.0 == best }.map(\.1), length).path)
    }

    private func remember(_ key: String, _ path: String) -> String {
        lock.lock()
        memo[key] = path
        lock.unlock()
        return path
    }

    private func closest(_ files: [URL], _ length: Double) -> URL {
        guard files.count > 1, length > 0 else { return files[0] }
        let scored = files.map { (abs((Self.length(of: $0) ?? 0) - length), $0) }
        let best = scored.min { $0.0 < $1.0 }!
        return best.0 < Self.lengthTolerance ? best.1 : files[0]
    }

    /// A track's length in seconds.
    static func length(of file: URL) -> Double? {
        guard let f = try? AVAudioFile(forReading: file), f.processingFormat.sampleRate > 0 else { return nil }
        return Double(f.length) / f.processingFormat.sampleRate
    }

    /// Lower-case words without accents: "Café del Mar" → ["cafe", "del", "mar"].
    static func words(_ s: String) -> [String] {
        s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: nil).lowercased()
            .split(whereSeparator: { !($0.isASCII && ($0.isLetter || $0.isNumber)) }).map(String.init)
    }
}
