// The track's genre (one word), and the program it gets: a chip for every track, and a banner that stands
// out for a program of its own (cinematic: every hit played by its own fixtures; the lightshow, switched on by
// hand: the same, as a show piece that builds up).
import AmadeusKit
import SwiftUI

enum Genre {
    static func symbol(_ genre: String) -> String {
        switch genre {
        case "cinematic": "film.stack"
        case "classical": "music.quarternote.3"
        case "ambient": "cloud"
        case "rock", "metal": "guitars"
        case "hiphop", "rnb": "music.mic"
        case "jazz", "funk": "music.note.list"
        case "disco": "sparkles"
        case "hardcore": "bolt.fill"
        case "pop", "latin", "reggaeton": "music.note"
        default: "waveform"
        }
    }

    static func source(_ s: String) -> String {
        switch s {
        case "you": "Your choice"
        case "ai": "From the artist and title (Decisions API)"
        case "tag": "From the file's genre tag"
        case "sound": "From its sound (the style model)"
        default: "From the audio: groove, bass and tempo"
        }
    }
}

/// "TECHNO", small; "POP → HOUSE" when the set plays it in another genre's style.
struct GenreChip: View {
    let genre: String
    var source = ""
    var style = ""

    private var restyled: Bool { !style.isEmpty && style != genre }

    var body: some View {
        if !genre.isEmpty {
            Label(restyled ? "\(genre.uppercased()) → \(style.uppercased())" : genre.uppercased(),
                  systemImage: Genre.symbol(genre))
                .font(.caption2.weight(.bold))
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(.quaternary, in: .capsule)
                .help("Genre: \(genre). \(Genre.source(source))."
                      + (restyled ? " Lit in the set's \(style) style, so the set looks like one show." : ""))
        }
    }
}

/// A program of its own: said loudly.
struct ProgramBanner: View {
    let program: String

    private var lightshow: Bool { program == "lightshow" }

    var body: some View {
        if program == "cinematic" || lightshow {
            HStack(spacing: 10) {
                Image(systemName: lightshow ? "sparkles" : "film.stack").font(.title2.weight(.semibold))
                VStack(alignment: .leading, spacing: 1) {
                    Text(lightshow ? "LIGHTSHOW" : "CINEMATIC PROGRAM").font(.callout.weight(.heavy)).tracking(1.5)
                    Text(lightshow ? "Every hit played, building up section by section"
                         : "Every hit played by its own fixtures, exactly on time").font(.caption).opacity(0.85)
                }
                Spacer(minLength: 0)
            }
            .foregroundStyle(.white)
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(
                LinearGradient(colors: [Color(red: 0.95, green: 0.45, blue: 0.1), Color(red: 0.55, green: 0.1, blue: 0.6)],
                               startPoint: .leading, endPoint: .trailing),
                in: .rect(cornerRadius: 12)
            )
            .help(lightshow
                ? "You switched the Lightshow on: every hit is played by its own lights. One section starts, the others join phrase by phrase, each with an instrument of its own, until the whole rig plays at the climax."
                : "A film-score track: no beat grid. The hits are found where they are, sorted into voices, and every voice plays its own fixtures; the biggest hits play the whole rig.")
        }
    }
}
