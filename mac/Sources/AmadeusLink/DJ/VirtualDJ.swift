// VirtualDJ's streamed tracks (Spotify) on the DJ laptop. Its plugin reports them as "netsearch://" + a two-letter
// service + the service's id ("netsearch://sp1fI4E7jeOiyfa3LmwNnD0o"): no file to send. VirtualDJ's database.xml
// names them (<Tags Author= Title=>, <Infos SongLength=>), so Amadeus Link adds what the lighting computer needs
// to fetch a copy of the same recording itself, as for djay (a port of streamed.py's vdj_streams).
import Foundation

final class VirtualDJStreams: @unchecked Sendable {
    static let services = ["sp": "spotify", "td": "tidal", "dz": "deezer", "sc": "soundcloud", "bp": "beatport", "bs": "beatsource"]
    static let database = FileManager.default.homeDirectoryForCurrentUser
        .appending(path: "Library/Application Support/VirtualDJ/database.xml")

    let path: URL
    private var known: [String: StreamedTrack] = [:]
    private var mtime: Date?

    init(path: URL = VirtualDJStreams.database) { self.path = path }

    /// "netsearch://sp…" → the service and its id; nil for anything else.
    static func netsearch(_ file: String) -> (service: String, id: String)? {
        guard file.hasPrefix("netsearch://") else { return nil }
        let rest = file.dropFirst("netsearch://".count)
        guard rest.count > 2, rest.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else { return nil }
        let code = String(rest.prefix(2))
        return (services[code] ?? code, String(rest.dropFirst(2)))
    }

    /// The streamed track a deck reports, read again when unknown (or its length still unknown) and the database changed.
    func find(_ file: String) -> StreamedTrack? {
        guard Self.netsearch(file) != nil else { return nil }
        if known[file] == nil || known[file]!.length == 0,
           let m = (try? FileManager.default.attributesOfItem(atPath: path.path))?[.modificationDate] as? Date, m != mtime {
            mtime = m
            if let data = try? Data(contentsOf: path) { known = Self.parse(data) }
        }
        return known[file]
    }

    static func parse(_ data: Data) -> [String: StreamedTrack] {
        let p = DatabaseParser()
        let x = XMLParser(data: data)
        x.delegate = p
        x.parse()
        return p.found
    }

    /// A length from the database: a whole number of seconds is VirtualDJ's guess before it has the stream (unknown).
    static func length(_ text: String?) -> Double {
        guard let l = text.flatMap(Double.init) else { return 0 }
        return l == l.rounded() ? 0 : l
    }

    /// A plugin packet with its streamed decks named: "file" "" (nothing to fetch from this laptop), the title, the
    /// artist and "stream" (the lighting computer fetches a copy). Unchanged when no deck streams.
    func enrich(_ packet: Data) -> Data {
        guard packet.range(of: Data("netsearch://".utf8)) != nil,
              var obj = (try? JSONSerialization.jsonObject(with: packet)) as? [String: Any],
              let decks = obj["decks"] as? [[String: Any]] else { return packet }
        obj["decks"] = decks.map { d -> [String: Any] in
            guard let file = d["file"] as? String, let ns = Self.netsearch(file) else { return d }
            var d = d
            d["file"] = ""
            guard let s = find(file) else { return d }  // not named yet: listed, dark
            d["title"] = s.title
            d["artist"] = s.artist
            if s.length > 0 { d["len"] = s.length }
            d["stream"] = ["service": ns.service, "id": ns.id, "isrc": ""]
            return d
        }
        return (try? JSONSerialization.data(withJSONObject: obj)) ?? packet
    }
}

private final class DatabaseParser: NSObject, XMLParserDelegate {
    var found: [String: StreamedTrack] = [:]
    private var file: String?
    private var title = "", artist = "", length = 0.0

    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName: String?,
                attributes a: [String: String]) {
        switch name {
        case "Song":
            file = VirtualDJStreams.netsearch(a["FilePath"] ?? "") != nil ? a["FilePath"] : nil
            title = ""; artist = ""; length = 0
        case "Tags" where file != nil:
            title = a["Title"] ?? ""
            artist = a["Author"] ?? ""
        case "Infos" where file != nil:
            length = VirtualDJStreams.length(a["SongLength"])
        default: break
        }
    }

    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
        guard name == "Song", let f = file, !title.isEmpty, let ns = VirtualDJStreams.netsearch(f) else { return }
        found[f] = StreamedTrack(service: ns.service, id: ns.id, title: title, artist: artist, length: length)
        file = nil
    }
}
