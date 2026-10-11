"""Live mode: follow a DJ's mix: VirtualDJ on this computer or on a DJ laptop (Decisive Link), or another DJ
software through its integration (`--source NAME`, see decisive/show/sources).

VirtualDJ's DecisiveLink plugin streams every deck's track, position, play state, tempo and volume. Every
track that appears is analysed and planned (rules immediately, the AI director in the background), and each
deck plays its own light show at exactly the position VirtualDJ reports, so seeks, loops, pitch changes and
cuts are followed. When several decks are audible, colours and brightness blend by volume; the moving heads
follow the dominant deck.
"""

from __future__ import annotations

import asyncio
import errno
import json
import threading
import time
from pathlib import Path

from decisive import paths
from decisive.dmx.outputs import drives_real_lights, open_output
from decisive.engine import State
from decisive.engine.realism import Realism
from decisive.library import fixtures as fxlib
from decisive.show import feed as feedlib
from decisive.show.mixer import Mixer
from decisive.show.tracks import TrackShows
from decisive.show.vdj import UDP_PORT, Listener
from decisive.web.server import serve as serve_http

DEFAULT_LINK_PORT = 7123
DJ_LOOKUP_TRIES = 5  # × 3 s: how long to look for a DJ laptop by name before giving up


def port_in_use_message() -> str:
    """Why the plugin's port is taken, and what to do: the Decisive Link app on this Mac, or another engine."""
    import subprocess

    def running(name: str) -> bool:
        return subprocess.run(["pgrep", "-f", name], capture_output=True).returncode == 0

    if running("DecisiveLink.app") or running("Decisive Link.app"):
        return (
            f"VirtualDJ's port ({UDP_PORT}) is taken by the Decisive Link app on this Mac. Decisive Link is for a DJ "
            "laptop that isn't this computer: quit it here and start the live show again. (If VirtualDJ runs on "
            "another laptop, start with that laptop instead: --remote auto --code NNNN.)"
        )
    if running("decisive live") or running("-m decisive live"):
        return f"VirtualDJ's port ({UDP_PORT}) is taken by another live show already running: stop that one first."
    return f"VirtualDJ's port ({UDP_PORT}) is taken by another program on this computer: close it and try again."


def open_listener(remote: str | None, code: str | None, cache: Path, source: str | None = None, opts=None):
    """The decks: from the plugin on this computer, or (`remote`) from a DJ laptop's Decisive Link app:
    'dj:NAME' (its Bonjour name, as the Mac app lists it), 'auto' (the first one found) or HOST[:PORT];
    or (`source`) from another DJ software's integration, with its options."""
    if source and source != "vdj":
        from decisive.show.sources import open_source

        return open_source(source, **(opts or {}))
    if not remote:
        try:
            return Listener()
        except OSError as e:
            if e.errno != errno.EADDRINUSE:
                raise
            raise SystemExit(port_in_use_message()) from None
    from decisive.show.link import RemoteListener, browse, resolve

    if remote.startswith("dj:"):
        found = None
        for _ in range(DJ_LOOKUP_TRIES):  # the DJ laptop's app may still be starting up
            found = resolve(remote[3:])
            if found:
                break
        if not found:
            raise SystemExit(f"Can't find the DJ laptop '{remote[3:]}' on the network")
        host, port = found
    elif remote == "auto":
        found = browse()
        if not found:
            raise SystemExit("No Decisive Link found on the network. Is it switched on on the DJ laptop?")
        name, host, port = found[0]
        print(f"Decisive Link: found {name} at {host}:{port}")
    else:
        host, _, p = remote.rpartition(":")
        host, port = (host, int(p)) if host else (remote, DEFAULT_LINK_PORT)
    if not code:
        raise SystemExit("--code: the 4-digit pairing code the Decisive Link app shows on the DJ laptop")
    return RemoteListener(host, port, code, cache)


class DirectorFollower:
    """Without --director, the show uses the set's decision model and follows changes the setup page saves."""

    def __init__(self, show, shows: TrackShows):
        self.show, self.shows = show, shows
        self.mtime = show.mtime()
        self.checked = 0.0

    def poll(self, now: float):
        if now - self.checked < 1.0:
            return
        self.checked = now
        try:
            m = self.show.mtime()
            if m != self.mtime:
                self.mtime = m
                self.shows.set_director(self.show.load().get("director", "rules"))
        except (OSError, json.JSONDecodeError):
            pass


class Bands:
    """The spectrum of what is playing (the visualiser's meters): each deck's bands, weighted by volume."""

    def __init__(self):
        self.cache: dict[int, list] = {}  # per analysis

    def at(self, parts) -> list[float]:
        total, acc = 0.0, None
        for w, _, _, show, t, _ in parts:
            a = show[0]
            arrs = self.cache.get(id(a))
            if arrs is None:
                arrs = self.cache[id(a)] = [a.band_norm(k) for k in a.bands_db]
            f = min(max(int(t * a.fps), 0), len(arrs[0]) - 1)
            vals = [float(b[f]) for b in arrs]
            acc = [x * w for x in vals] if acc is None else [p + x * w for p, x in zip(acc, vals)]
            total += w
        return [round(x / total, 3) for x in acc] if acc and total > 0 else [0, 0, 0, 0, 0]


def _health_line(hs: dict, listener: Listener, shows: TrackShows):
    """One line of vital signs (live --health)."""
    import resource

    now = time.monotonic()
    dt = now - hs["t0"]
    pkts = listener.packets - hs["packets"]
    decks = " ".join(
        f"{d.deck}:{'▶' if d.play else '■'}{d.pos:.1f}s" for d in sorted(listener.decks.values(), key=lambda d: d.deck)
    )
    silent = now - listener.last if listener.last else float("inf")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6  # bytes on macOS → MB (peak)
    dj = getattr(listener, "label", "VirtualDJ")
    flag = f"  ⚠ {dj} sends nothing" if pkts == 0 else ("  ⚠ light loop late" if hs["worst"] > 0.1 else "")
    print(
        f"  ♥ {time.strftime('%H:%M:%S')} {dj} {pkts / dt:4.1f} pkt/s (last {min(silent, 999):.1f}s ago) "
        f"decks [{decks}] · loop {hs['frames'] / dt:4.1f} fps, worst late {hs['worst'] * 1000:.0f} ms · "
        f"shows {len(shows.shows)} · threads {threading.active_count()} · peak mem {rss:.0f} MB{flag}",
        flush=True,
    )
    if hasattr(listener, "health"):  # VirtualDJ on another computer: the link's own vital signs
        print(f"    {listener.health()}", flush=True)
    hs.update(t0=now, frames=0, worst=0.0, packets=listener.packets)


async def run(
    rig: dict,
    director: str | None,
    artnet_ip: str | None,
    http_port: int = 8080,
    ws_port: int = 8765,
    cache: Path = paths.CACHE,
    show=None,
    health: float = 0.0,
    remote: str | None = None,
    code: str | None = None,
    source: str | None = None,
    source_opts: dict | None = None,
):
    """`artnet_ip`: None = visualiser only, "rig" = the set's output, an IP = that network node.
    `health`: every that many seconds print one line: packets from VirtualDJ, deck positions, how well the
    light loop keeps time, threads and memory (to tell a VirtualDJ stall from one of ours)."""
    from websockets.asyncio.server import serve

    from decisive.rig import store

    show = show or store.current()
    listener = open_listener(remote, code, cache, source, source_opts)
    dj = getattr(listener, "label", "VirtualDJ")
    follow_set = director is None  # no --director: the set's decision model, following changes to it
    director = director or rig.get("director", "rules")
    sender = open_output(rig, None if artnet_ip == "rig" else artnet_ip) if artnet_ip else None
    shows = TrackShows(rig, director, cache, real_output=drives_real_lights(sender, rig))
    follower = DirectorFollower(show, shows) if follow_set else None
    universes = sorted({f["universe"] for f in rig["fixtures"]})
    ids = [e["id"] for e in rig["elements"]]
    period = 1.0 / rig["artnet"].get("fps", 40)
    real = Realism(rig)
    feed = feedlib.Feed(rig, real, period)
    mixer, bands = Mixer(rig), Bands()
    showing = None  # (deck, file, director, plan) the visualiser's hello describes

    httpd = serve_http(http_port, show)
    if remote:
        print(f"Live mode: VirtualDJ on {listener.name}, via Decisive Link.")
    elif source and source != "vdj":
        print(f"Live mode: following {listener.name}.")
    else:
        print(f"Live mode: waiting for VirtualDJ (DecisiveLink plugin as master effect, UDP {UDP_PORT}).")
    print(f"Visualiser: http://localhost:{http_port}   Director: {director}   (Ctrl+C to stop)")
    if sender:
        print(f"{sender.describe()}, universes {universes}")
    hs = {"t0": time.monotonic(), "frames": 0, "worst": 0.0, "packets": 0}
    next_tick, was_alive = time.monotonic(), False
    async with serve(feed.handler, "127.0.0.1", ws_port):
        try:
            while True:
                next_tick += period
                if health:
                    late = time.monotonic() - next_tick + period  # > 0: this frame started late
                    hs["worst"], hs["frames"] = max(hs["worst"], late), hs["frames"] + 1
                    if time.monotonic() - hs["t0"] >= health:
                        _health_line(hs, listener, shows)
                now = time.monotonic()
                if follower:
                    follower.poll(now)
                alive = listener.alive()
                if alive != was_alive:
                    print(f"  {dj} connected" if alive else f"  {dj} silent: lights dark")
                    was_alive = alive

                # every audible deck renders its own show at its own position
                parts, decks = [], []
                for deck in sorted(listener.decks.values(), key=lambda d: d.deck) if alive else []:
                    show = shows.get(deck.file) if deck.file else None  # no file: a track not on this computer
                    decks.append(
                        {
                            "deck": deck.deck,
                            "track": Path(deck.file).stem if deck.file else f"{deck.artist} – {deck.title}".strip(" –"),
                            "vol": round(deck.vol, 2),
                            "play": deck.play,
                            "ready": show is not None,
                            "status": shows.progress(deck.file) if deck.file else {"missing": True},
                            "genre": show[0].genre if show else "",
                            "style": show[0].style if show else "",
                        }
                    )
                    weight = deck.vol if deck.play else 0.0
                    if show is None or weight <= 0.01:
                        continue
                    a, _, engine, _ = show
                    t = min(max(deck.now(now), 0.0), a.duration - 0.05)
                    i, states = engine.render(t)
                    parts.append((weight, states, deck, show, t, i))

                engine = None
                if parts:
                    states, dom = mixer.mix(parts)
                    _, _, deck, show, t, i = dom
                    a, plan, engine, used = show
                    key = (deck.deck, deck.file, used, id(plan))
                    if key != showing:
                        showing = key
                        title = feedlib.track_title(deck.file, deck.deck)
                        feed.set_hello(feedlib.hello(a, plan, rig, real, title=title, director=used))
                        print(f"  ▶ heads follow deck {deck.deck}: {Path(deck.file).name}")
                else:
                    states, i, t = {eid: State() for eid in ids}, 0, 0.0

                if sender:
                    unis: dict[int, bytearray] = {}
                    for f in rig["fixtures"]:
                        fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
                    sender.send(unis)
                if feed.watched:
                    b, ph, _ = engine.beat_info(t) if engine else (0, 0.0, 0.5)
                    guard = feedlib.guard_notes(engine) if engine else {}
                    status = {
                        "t": round(t, 3),
                        "phrase": i,
                        "decks": decks,
                        "bp": round(b + ph, 3),
                        **({"link": listener.status()} if remote else {}),
                        **({"guard": guard} if guard else {}),
                    }

                    def fixtures(engine=engine, states=states, t=t, parts=parts):
                        lasers = engine.laser_beams(states, t) if engine and engine.lasers else None
                        return {"bands": bands.at(parts), **feed.fixture_fields(states, lasers)}

                    feed.send(status, fixtures)
                await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
        finally:
            if sender:
                sender.blackout(universes)
                sender.close()
            httpd.shutdown()
            print("Stopped" + (" (DMX blacked out)" if sender else ""))
