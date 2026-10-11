"""Shows: analyse and direct a track, play it, follow VirtualDJ live, watch it run."""

from __future__ import annotations

import asyncio
from pathlib import Path

from decisive import paths
from decisive.cli.common import add_dmx_arg, add_set_args
from decisive.show.sources import parse_opts


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

    p = sub.add_parser("live", help="follow a VirtualDJ mix (DecisiveLink plugin as master effect)")
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
        help="VirtualDJ on another computer: its Decisive Link app (HOST:PORT, dj:NAME, or 'auto' to find it)",
    )
    p.add_argument("--code", default=None, help="the pairing code the Decisive Link app shows")
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

    from decisive.audio.genre import GENRES

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
    return {
        "genre": genre_command,
        "analyze": analyze,
        "direct": direct_or_play,
        "play": direct_or_play,
        "live": live,
        "monitor": monitor,
        "probe": probe,
    }


def analyze(args):
    from decisive.audio.analysis import analyze as run

    a = run(args.wav, paths.CACHE, tempo=args.tempo)
    print(f"{a.duration:.0f} s, {a.bpm:.1f} BPM, {len(a.beats)} beats, {len(a.phrases)} phrases, genre {a.genre}")


def genre_command(args):
    from decisive.audio import genre
    from decisive.audio.analysis import analyze as run

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
    from decisive.pipeline import get_plan, pick_director, separate_now
    from decisive.rig.loader import load_rig

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
    from decisive.show.player import play

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
    from decisive.rig.loader import load_rig
    from decisive.show.live import run

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
        help="another DJ software than VirtualDJ (`decisive probe` lists them)",
    )
    p.add_argument("--opt", action="append", metavar="KEY=VALUE", help="an option for that DJ software's integration")


def probe(args):
    from decisive.show import probe as probelib
    from decisive.show.sources import SOURCES

    if not args.source:
        for name, e in SOURCES.items():
            print(f"{name:10} {e.position:8} {e.about}\n{'':19} verified: {e.verified}")
        return
    probelib.run(args.source, parse_opts(args.opt), args.seconds, args.emit, args.record)


def monitor(args):
    from decisive.show.monitor import run

    try:
        run(args.interval)
    except KeyboardInterrupt:
        pass
