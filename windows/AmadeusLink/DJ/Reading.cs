// What Amadeus Link reads from a DJ software other than VirtualDJ (djay Pro, Mixxx) and how it passes it on:
// as the AmadeusLink plugin's packets, so the lighting computer can't tell them apart (the same format as
// amadeus/show/probe.py plugin_packet). VirtualDJ's own plugin sends these packets itself.
// The readers themselves (djay Pro through UI Automation, Mixxx through MIDI) are ported next to this file.
using System.Diagnostics;
using System.Text.Json;

namespace AmadeusLink;

/// One deck as the DJ software reports it.
public sealed record DeckReading
{
    public int Deck { get; init; }
    public string File { get; init; } = "";    // the track on this laptop ("" while unknown: not passed on)
    public double Pos { get; init; }           // seconds, at `Received`
    public double Length { get; init; }
    public bool Play { get; init; }
    public double Bpm { get; init; }
    public double Bpm0 { get; init; }
    public double Vol { get; init; }           // what reaches the master: channel fader × crossfader, 0..1
    public double Received { get; init; }      // monotonic seconds
    public string Title { get; init; } = "";
    public string Artist { get; init; } = "";
    public string Id { get; init; } = "";
    public double Rate { get; init; }          // playback speed when the DJ software reports it
    public bool Sync { get; init; }            // synced to Ableton Link: the lighting computer reads the beat from Link itself
    public StreamedTrack? Stream { get; init; } // streamed (Spotify): no file here; the lighting computer fetches a copy of the recording

    public double Speed => Rate > 0 ? Rate : (Bpm0 > 1 && Bpm > 1 ? Bpm / Bpm0 : 1);

    public double Now(double t) => Play ? Pos + (t - Received) * Speed : Pos;

    /// "2: ▶ Artist – Title", and why it isn't passed on when it has no file here.
    public string Line
    {
        get
        {
            var what = Title.Length == 0 ? Path.GetFileName(File) : (Artist.Length == 0 ? Title : $"{Artist} – {Title}");
            var why = Stream is { } s ? $"  ({Formatting.Capitalized(s.Service)}: the lighting computer fetches a copy)"
                : File.Length == 0 && Title.Length > 0 ? "  (no file on this laptop: not sent)" : "";
            return $"{Deck}: {(Play ? "▶" : "■")} {(what.Length == 0 ? "no track" : what)}{why}";
        }
    }
}

/// A track the DJ software streams, as its library knows it (the recording: the service's id and the ISRC).
public sealed record StreamedTrack(string Service, string Id, string Title, string Artist, string Isrc = "", double Length = 0);

/// A DJ software Amadeus Link reads itself.
public interface IDJReader
{
    /// The DJ software's name, as the lighting computer shows it.
    string App { get; }
    /// What the DJ should know or do ("start Mixxx after Link"), "" when fine.
    string Note { get; }
    /// The decks right now.
    IReadOnlyList<DeckReading> Decks(double now);
    /// Every deck the DJ software shows, one line each, with why a deck isn't passed on (for Link's window).
    string Summary(double now);
    void Stop();
}

public static class Packet
{
    /// The decks as the AmadeusLink plugin sends them, positions brought to `now`. Decks with neither a file nor a
    /// stream stay out: the lighting computer can only light a track it can get. A streamed deck has no file
    /// ("file": "") and says which recording it is ("stream"); the lighting computer fetches a copy (streamed.py).
    public static byte[]? Make(string app, IReadOnlyList<DeckReading> decks, double now, double start)
    {
        using var ms = new MemoryStream();
        using (var w = new Utf8JsonWriter(ms))
        {
            w.WriteStartObject();
            w.WriteNumber("t", (long)((now - start) * 1000));
            w.WriteString("app", app);
            w.WriteNumber("master", 0);
            w.WriteStartArray("decks");
            foreach (var d in decks.Where(d => d.File.Length > 0 || d.Stream is not null).OrderBy(d => d.Deck))
            {
                w.WriteStartObject();
                w.WriteNumber("deck", d.Deck);
                w.WriteString("file", d.File);
                w.WriteNumber("pos", Round4(d.Now(now)));
                w.WriteNumber("len", d.Length);
                w.WriteNumber("play", d.Play ? 1 : 0);
                w.WriteNumber("bpm", d.Bpm);
                w.WriteNumber("bpm0", d.Bpm0);
                w.WriteNumber("vol", Round4(d.Vol));
                if (d.Title.Length > 0) w.WriteString("title", d.Title);
                if (d.Artist.Length > 0) w.WriteString("artist", d.Artist);
                if (d.Id.Length > 0) w.WriteString("id", d.Id);
                if (d.Sync) w.WriteNumber("sync", 1);
                if (d.Stream is { } st && d.File.Length == 0)
                {
                    w.WriteStartObject("stream");
                    w.WriteString("service", st.Service);
                    w.WriteString("id", st.Id);
                    w.WriteString("isrc", st.Isrc);
                    w.WriteEndObject();
                }
                w.WriteEndObject();
            }
            w.WriteEndArray();
            w.WriteEndObject();
        }
        return ms.ToArray();
    }

    static double Round4(double x) => Math.Round(x * 10000, MidpointRounding.AwayFromZero) / 10000;
}

public static class Clock
{
    /// Monotonic seconds (the readers' clock).
    public static double Monotonic() => Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency;
}
