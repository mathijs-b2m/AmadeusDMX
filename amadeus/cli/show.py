"""Shows: analyse and direct a track, play it, follow VirtualDJ live, watch it run."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from amadeus import paths
from amadeus.cli.common import add_dmx_arg, add_set_args
from amadeus.show.sources import parse_opts


def add_commands(sub) -> dict:
    for name in ("analyze", "direct", "play"):
        p = sub.add_parser(
            name,
            help={
                "analyze": "beats, phrases and drops of a track",
                "direct": "the director's plan for a track",
                "play": "play a track with the lights and the visualiser",
            }[name],
        )
        p.add_argument("wav", type=Path, metavar="TRACK")
        p.add_argument("--tempo", choices=["half", "double"], help="the song is half / double as fast as detected")
        if name == "analyze":
            continue
        p.add_argument("--style", metavar="GENRE", help="light it in the house style of this genre (default: its own)")
        p.add_argument(
            "--director",
            default="auto",
            help="auto | openai | rules | ollama (local decision model nimble) | ollama:<decision model>",
        )
        p.add_argument("--redo", action="store_true", help="re-run the director even if a plan is cached")
        if name == "play":
            add_set_args(p)
            add_dmx_arg(p)
            p.add_argument("--mute", action="store_true", help="don't play audio (clock runs silently)")
            p.add_argument("--start", type=float, default=0.0, help="start position in seconds")
            p.add_argument("--port", type=int, default=8080)
            p.add_argument("--ws-port", type=int, default=8765, help="visualiser feed (open /?ws=PORT for another)")

    p = sub.add_parser("live", help="follow a VirtualDJ mix (AmadeusLink plugin as master effect)")
    p.add_argument(
        "--director",
        default=None,
        help="rules | openai | ollama:<model> (default: the rig's setting, switchable in /setup.html)",
    )
    add_dmx_arg(p)
    add_set_args(p)
    p.add_argument(
        "--remote",
        metavar="HOST:PORT",
        default=None,
        help="VirtualDJ on another computer: its Amadeus Link app (HOST:PORT, dj:NAME, or 'auto' to find it)",
    )
    p.add_argument("--code", default=None, help="the pairing code the Amadeus Link app shows")
    _add_source_args(p)
    p.add_argument("--ws-port", type=int, default=8765, help="visualiser feed (a second show next to another)")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument(
        "--health",
        type=float,
        nargs="?",
        const=5.0,
        default=0.0,
        metavar="SECONDS",
        help="print vital signs every few seconds (default 5): VirtualDJ packets, decks, loop timing",
    )

    from amadeus.audio.genre import GENRES

    p = sub.add_parser("genre", help="a track's genre (one word): show it, or set your own (auto: back to automatic)")
    p.add_argument("wav", type=Path, metavar="TRACK")
    p.add_argument("genre", nargs="?", choices=[*GENRES, "auto"])

    p = sub.add_parser("probe", help="watch a DJ software integration: decks, events, timing; record or pass it on")
    p.add_argument("source", nargs="?", help="which DJ software (leave out for the list)")
    p.add_argument("--opt", action="append", metavar="KEY=VALUE", help="an option for the integration (repeatable)")
    p.add_argument("--seconds", type=float, default=0.0, help="stop after this long (default: Ctrl+C)")
    p.add_argument("--emit", metavar="HOST:PORT", help="send the decks on in the plugin's format (127.0.0.1:9123)")
    p.add_argument("--record", type=Path, metavar="FILE", help="keep every reading (JSON lines) for --source replay")

    p = sub.add_parser("monitor", help="watch VirtualDJ + live mode: CPU, memory, threads, GPU, crashes")
    p.add_argument("--interval", type=float, default=1.0)

    p = sub.add_parser("instruments", help="which instruments play in a track (MTG-Jamendo models, non-commercial)")
    p.add_argument("wav", type=Path, nargs="?", metavar="TRACK", help="show its instruments over time")
    p.add_argument("--download", action="store_true", help="fetch the two models (~21 MB, CC BY-NC-SA 4.0)")

    p = sub.add_parser("synctest", help="a test track with beeps, and a listener: how far the show is from the music")
    p.add_argument("action", choices=["make", "listen"], help="make: write the track; listen: measure while it plays")
    p.add_argument("--out", type=Path, default=Path.home() / "Music" / "Amadeus DMX", help="where make writes it")
    p.add_argument("--seconds", type=float, default=200.0, help="listen this long (the track is three minutes)")
    p.add_argument("--ws-port", type=int, default=8765, help="the running show's feed")
    p.add_argument("--lead-ms", type=float, default=None, help="the show's light lead (default: the active rig's)")
    return {
        "genre": genre_command,
        "analyze": analyze,
        "direct": direct_or_play,
        "play": direct_or_play,
        "live": live,
        "monitor": monitor,
        "probe": probe,
        "synctest": synctest,
        "instruments": instruments_command,
    }


def instruments_command(args):
    from amadeus.audio import instruments, stems

    if args.download:
        print("The MTG-Jamendo instrument models (Music Technology Group, UPF) are licensed CC BY-NC-SA 4.0:")
        print("non-commercial use only; a proprietary license is available from the MTG.")
        instruments.download()
        print(f"Downloaded to {instruments.MODELS}")
    if not instruments.available():
        raise SystemExit("Not installed: `pip install onnxruntime` and `amadeus instruments --download`")
    if not args.wav:
        return
    ins = stems.load_instruments(args.wav)
    if ins is None:
        raise SystemExit("Separate the track first (it happens in a live show or `amadeus play`)")
    for t0 in range(0, int(ins["t"][-1]) + 1, 15):
        m = (ins["t"] >= t0) & (ins["t"] < t0 + 15)
        if m.any():
            mean = ins["probs"][m].mean(0)
            top = ", ".join(f"{ins['names'][j]} {mean[j]:.2f}" for j in mean.argsort()[::-1][:3] if mean[j] >= 0.15)
            print(f"{t0 // 60}:{t0 % 60:02d}  {top}")


def synctest(args):
    from amadeus.show import synctest as st

    side = args.out / f"{st.NAME}.json"
    if args.action == "make":
        wav, side = st.make(args.out)
        print(f"{wav}\n{side}\nAdd the track to the DJ software, start the live show, then: amadeus synctest listen")
        return
    if not side.exists():
        raise SystemExit(f"No test track in {args.out}: run `amadeus synctest make` first")
    if args.lead_ms is None:
        from amadeus.rig import store
        from amadeus.rig.loader import load_rig_dict
        from amadeus.show.clock import light_lead

        lead = light_lead(load_rig_dict(store.current().load()))
    else:
        lead = args.lead_ms / 1000
    result = st.listen(side, args.seconds, args.ws_port, lead)
    print("Result:", json.dumps(result))
    if "offset_ms" in result:
        off = result["offset_ms"]
        print(
            f"The show is {abs(off):.0f} ms {'ahead of' if off > 0 else 'behind'} the music you hear "
            f"(10-90% spread {result['spread_ms']:.0f} ms"
            + (f", drift {result['drift_ms_per_min']:+.0f} ms per minute)" if "drift_ms_per_min" in result else ")")
        )


def analyze(args):
    from amadeus.audio.analysis import analyze as run

    a = run(args.wav, paths.CACHE, tempo=args.tempo)
    print(f"{a.duration:.0f} s, {a.bpm:.1f} BPM, {len(a.beats)} beats, {len(a.phrases)} phrases, genre {a.genre}")


def genre_command(args):
    from amadeus.audio import genre
    from amadeus.audio.analysis import analyze as run

    a = run(args.wav, paths.CACHE, verbose=False)
    if args.genre:
        genre.set_override(a, None if args.genre == "auto" else args.genre)
        a = run(args.wav, paths.CACHE, verbose=False)
    program = genre.PROGRAMS.get(a.genre)
    sources = {"you": "your choice", "ai": "Decisions API, from the artist and title", "tag": "the file's tag"}
    print(f"{a.genre}  (from {sources.get(a.genre_source, 'the audio')})")
    print(f"  measured: {a.genre_facts}")
    if program:
        print(f"  program: {a.genre} — {program}")


def direct_or_play(args):
    from amadeus.pipeline import get_plan, pick_director, separate_now
    from amadeus.rig.loader import load_rig

    if args.director == "auto" and args.cmd == "play":  # the model chosen on the setup page
        args.director = args.show.load().get("director", "auto")
    director = pick_director(args.director, args.wav, args.redo, args.tempo)
    rig = load_rig(args.show) if args.cmd == "play" else None
    separate_now(args.wav)
    a, plan = get_plan(args.wav, director, args.redo, args.tempo, rig=rig, style_genre=args.style)
    if a.style:
        print(f"Style: {a.style}" + ("" if a.style == a.genre else f" (the track is {a.genre})"))
    if args.cmd != "play":
        return
    from amadeus.show.player import play

    try:
        asyncio.run(
            play(
                a,
                plan,
                rig,
                director=director,
                audio=not args.mute,
                artnet_ip=args.artnet,
                start=args.start,
                http_port=args.port,
                ws_port=args.ws_port,
            )
        )
    except KeyboardInterrupt:
        pass


def live(args):
    from amadeus.rig.loader import load_rig
    from amadeus.show.live import run

    try:
        asyncio.run(
            run(
                load_rig(args.show),
                args.director,
                args.artnet,
                http_port=args.port,
                cache=paths.CACHE,
                show=args.show,
                health=args.health,
                remote=args.remote,
                code=args.code,
                source=args.source,
                source_opts=parse_opts(args.opt),
                ws_port=args.ws_port,
            )
        )
    except KeyboardInterrupt:
        pass


def _add_source_args(p):
    p.add_argument(
        "--source",
        default=None,
        metavar="NAME",
        help="another DJ software than VirtualDJ (`amadeus probe` lists them)",
    )
    p.add_argument("--opt", action="append", metavar="KEY=VALUE", help="an option for that DJ software's integration")


def probe(args):
    from amadeus.show import probe as probelib
    from amadeus.show.sources import SOURCES

    if not args.source:
        for name, e in SOURCES.items():
            print(f"{name:10} {e.position:8} {e.about}\n{'':19} verified: {e.verified}")
        return
    probelib.run(args.source, parse_opts(args.opt), args.seconds, args.emit, args.record)


def monitor(args):
    from amadeus.show.monitor import run

    try:
        run(args.interval)
    except KeyboardInterrupt:
        pass
