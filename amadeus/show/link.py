"""Amadeus Link: VirtualDJ on another computer (the DJ's laptop) drives the show over the network.

The DJ runs the small "Amadeus Link" app next to VirtualDJ (with the AmadeusLink plugin as before). It
advertises itself with Bonjour (_amadeuslink._tcp: found with macOS's dns-sd, on Windows with zeroconf, no
Bonjour service needed) and shows a 4-digit pairing code. The lighting computer connects with that code
(`amadeus live --remote HOST:PORT --code 1234`, or "Nearby DJs" in the app).

Protocol v1 (all JSON lines over TCP, then UDP datagrams):

  pairing (TCP, the service's port)
    → {"hello": "amadeus", "v": 1, "nonce": c}                    c, s: 16 random bytes, hex
    ← {"v": 1, "name": "DJ laptop", "nonce": s}
    → {"proof": HMAC(code, "pair" s c), "udp": <port>}
    ← {"ok": true, "session": id}   (or {"ok": false, "error": ...} and the connection closes)
    session key = HMAC(code, "key" s c); the connection stays open (keepalive: {"ping": n} → {"pong": n})

  deck state (UDP, DJ laptop → lighting computer, ~25 per second)
    <json> "|" <first 16 bytes of HMAC(key, json), hex>
    json = {"s": seq, "ts": <DJ laptop clock, ns>, "d": <the plugin's packet>}

  a track (TCP, a new connection per file)
    → {"file": <path as VirtualDJ reports it>, "session": id, "auth": HMAC(key, "file" path)}
    ← {"ok": true, "size": n, "mtime": t, "sha256": h} + n bytes
    Only files the plugin has reported are served.

Sync: every packet carries the DJ laptop's clock. The offset between the two clocks is the smallest
(arrival - sent) seen over the last seconds (NTP-style: the fastest packets have the least queueing), so
network jitter cancels out; the deck position is then extrapolated from the moment it was sent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import secrets
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from amadeus import paths
from amadeus.show.sources import streamed
from amadeus.show.vdj import Deck

SERVICE = "_amadeuslink._tcp"
VERSION = 1
OFFSET_WINDOW_S = 8.0  # the clock offset: smallest delay over this long
STALE_S = 1.0
JITTER_MS = float(os.environ.get("AMADEUS_LINK_JITTER_MS", 0))  # development: simulated network delay
FROZEN_S = 0.5


def _h(key: bytes, *parts: str | bytes) -> bytes:
    m = hmac.new(key, digestmod=hashlib.sha256)
    for p in parts:
        m.update(p.encode() if isinstance(p, str) else p)
    return m.digest()


def proof(code: str, s: str, c: str) -> str:
    return _h(code.encode(), "pair", s, c).hex()


def session_key(code: str, s: str, c: str) -> bytes:
    return _h(code.encode(), "key", s, c)


def sign(key: bytes, payload: bytes) -> str:
    return _h(key, payload)[:16].hex()


def _lines(sock: socket.socket):
    """JSON messages, one per line, from a TCP socket."""
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                yield json.loads(line)


def _send(sock: socket.socket, obj: dict):
    sock.sendall(json.dumps(obj).encode() + b"\n")


def browse(timeout: float = 3.0) -> list[tuple[str, str, int]]:
    """Amadeus Link services on the network: [(name, host, port)] (macOS dns-sd; elsewhere the zeroconf
    package, which needs no Bonjour service: Windows)."""
    if not shutil.which("dns-sd"):
        return _zeroconf(timeout)
    found: list[tuple[str, str, int]] = []
    try:
        p = subprocess.Popen(["dns-sd", "-B", SERVICE, "local."], stdout=subprocess.PIPE, text=True, encoding="utf-8")
        time.sleep(timeout)
        p.terminate()
        names = []
        for line in (p.stdout.read() if p.stdout else "").splitlines():
            parts = line.split()
            if len(parts) >= 7 and parts[1] == "Add" and SERVICE.split(".")[0] in line:
                names.append(" ".join(parts[6:]))
        for name in dict.fromkeys(names):
            q = subprocess.Popen(
                ["dns-sd", "-L", name, SERVICE, "local."], stdout=subprocess.PIPE, text=True, encoding="utf-8"
            )
            time.sleep(1.0)
            q.terminate()
            for line in (q.stdout.read() if q.stdout else "").splitlines():
                if "can be reached at" in line:
                    hostport = line.split("can be reached at")[1].split()[0]
                    host, port = hostport.rsplit(":", 1)
                    found.append((name, host.rstrip("."), int(port)))
                    break
    except FileNotFoundError:
        pass
    return found


def resolve(name: str, timeout: float = 3.0) -> tuple[str, int] | None:
    """An Amadeus Link service by its name (as Bonjour shows it) → (host, port)."""
    if not shutil.which("dns-sd"):
        hit = _zeroconf(timeout, name)
        return (hit[0][1], hit[0][2]) if hit else None
    try:
        q = subprocess.Popen(
            ["dns-sd", "-L", name, SERVICE, "local."], stdout=subprocess.PIPE, text=True, encoding="utf-8"
        )
        time.sleep(timeout)
        q.terminate()
        for line in (q.stdout.read() if q.stdout else "").splitlines():
            if "can be reached at" in line:
                host, port = line.split("can be reached at")[1].split()[0].rsplit(":", 1)
                return host.rstrip("."), int(port)
    except FileNotFoundError:
        pass
    return None


def _zeroconf(timeout: float, name: str | None = None) -> list[tuple[str, str, int]]:
    """Browse (or, given a name, resolve that one) with python-zeroconf: [(name, address, port)], IPv4 first."""
    try:
        from zeroconf import IPVersion, ServiceBrowser, Zeroconf
    except ImportError:
        print("  Amadeus Link: can't look on the network without the zeroconf package (pip install zeroconf)")
        return []
    kind = SERVICE + ".local."
    zc = Zeroconf()
    try:
        names: list[str] = [f"{name}.{kind}"] if name else []
        if not name:

            class Found:
                def add_service(self, zc, type_, full):
                    names.append(full)

                def update_service(self, zc, type_, full):
                    pass

                def remove_service(self, zc, type_, full):
                    pass

            ServiceBrowser(zc, kind, Found())
            time.sleep(timeout)
        found = []
        for full in dict.fromkeys(names):
            info = zc.get_service_info(kind, full, timeout=int(timeout * 1000) if name else 1000)
            addrs = (info.parsed_addresses(IPVersion.V4Only) or info.parsed_addresses()) if info else []
            if info and info.port and addrs:
                found.append((full.removesuffix("." + kind), addrs[0], int(info.port)))
        return found
    finally:
        zc.close()


class RemoteListener:
    """Like vdj.Listener (decks, master, last, packets, alive()), but the decks come from a DJ laptop over
    the network. Tracks are fetched once into the cache; a deck counts from the moment its track is here."""

    def __init__(self, host: str, port: int, code: str, cache_dir: Path = paths.CACHE):
        self.host, self.port, self.code = host, port, code
        self.cache = cache_dir / "remote"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.decks: dict = {}
        self.master = 0
        self.last = 0.0
        self.packets = 0
        self.lost = 0
        self.name = host
        self.moved: dict[int, tuple[float, float]] = {}
        self.delays: deque = deque()  # (arrival, arrival - sent): the clock offset estimate
        self.offset = None
        self.jitter_ms = 0.0
        self.local: dict[str, str] = {}  # remote path → cached local path
        self.transfers: dict[str, str] = {}  # remote path → "running" | "done" | "failed: …"
        self.seq = -1
        self.connected = False
        self.error = ""
        self.ableton = None  # Ableton Link on this computer, for decks synced to it (None: not joined yet)
        self.fetcher = None  # copies of streamed tracks (None: not needed yet, False: not allowed or no yt-dlp)
        self.dark: set[str] = set()  # streamed tracks said to stay dark (once each)
        # both IPv4 and IPv6: a DJ laptop found by its Bonjour name is often reached over IPv6
        self.udp = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.udp.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.udp.bind(("::", 0))
        self._pair()
        threading.Thread(target=self._receive, daemon=True).start()
        threading.Thread(target=self._keepalive, daemon=True).start()

    def _reconnect(self):
        """The link dropped (DJ app restarted, network blip): pair again with the same code until it's back."""
        while not self.connected:
            time.sleep(2.0)
            try:
                self.seq = -1  # a restarted DJ app counts from 0 again
                self.delays.clear()  # and has a new clock
                self.offset = None
                self._pair()
                self.error = ""
            except (OSError, SystemExit, StopIteration, ValueError) as e:
                self.error = f"reconnecting: {e}"

    # ---------------------------------------------------------------- pairing

    def _pair(self):
        self.ctl = socket.create_connection((self.host, self.port), timeout=5)
        c = secrets.token_hex(16)
        _send(self.ctl, {"hello": "amadeus", "v": VERSION, "nonce": c})
        lines = _lines(self.ctl)
        srv = next(lines)
        s = srv["nonce"]
        self.name = srv.get("name", self.host)
        _send(self.ctl, {"proof": proof(self.code, s, c), "udp": self.udp.getsockname()[1]})
        ok = next(lines)
        if not ok.get("ok"):
            raise SystemExit(f"Amadeus Link on {self.name}: {ok.get('error', 'pairing refused')} (check the code)")
        self.key = session_key(self.code, s, c)
        self.session = ok["session"]
        self.ctl.settimeout(None)
        self.connected = True
        print(f"  ⇄ paired with {self.name} ({self.host}:{self.port})", flush=True)

        def read():  # the DJ laptop's replies (pongs); the link is gone when this connection closes
            try:
                for _ in lines:
                    pass
            except (OSError, ValueError):
                pass
            if self.connected:
                self._lost("the DJ laptop closed the link")

        threading.Thread(target=read, daemon=True).start()

    def _lost(self, why: str):
        if not self.connected:
            return
        self.connected, self.error = False, why
        print(f"  ⚠ Amadeus Link: {why}; reconnecting …", flush=True)
        threading.Thread(target=self._reconnect, daemon=True).start()

    def _keepalive(self):
        n = 0
        while True:
            if not self.connected:
                time.sleep(0.5)
                continue
            try:
                _send(self.ctl, {"ping": n})
                n += 1
                time.sleep(2.0)
            except OSError as e:
                self._lost(f"link lost: {e}")

    # ---------------------------------------------------------------- deck state

    def _clock(self, sent: float, now: float) -> float:
        """The DJ laptop's send time on this computer's clock (NTP-style: smallest delay over a window)."""
        d = now - sent
        self.delays.append((now, d))
        while self.delays and now - self.delays[0][0] > OFFSET_WINDOW_S:
            self.delays.popleft()
        best = min(x for _, x in self.delays)
        if self.offset is None or abs(best - self.offset) > 0.0005:
            self.offset = best
        self.jitter_ms = (d - best) * 1000
        return sent + self.offset

    def _receive(self):
        while True:
            data, _ = self.udp.recvfrom(65535)
            now = time.monotonic()
            if JITTER_MS:  # development: pretend the network delays this packet (to test the sync)
                now += random.uniform(0, JITTER_MS) / 1000
            payload, _, sig = data.rpartition(b"|")
            if not payload or not hmac.compare_digest(sig.decode(errors="replace"), sign(self.key, payload)):
                continue  # not from our DJ laptop
            try:
                msg = json.loads(payload)
            except json.JSONDecodeError:
                continue
            seq = msg.get("s", 0)
            if seq <= self.seq:  # late or duplicate: a newer state is already here
                continue
            if self.seq >= 0 and seq > self.seq + 1:
                self.lost += seq - self.seq - 1
            self.seq = seq
            at = self._clock(msg["ts"] / 1e9, now)
            plugin = msg.get("d", {})
            self.master, self.last = int(plugin.get("master", 0)), now
            self.packets += 1
            decks, seen = {}, set()
            for d in sorted(plugin.get("decks", []), key=lambda x: x["deck"]):
                sig_ = (d["file"], round(d["pos"], 2), round(d["vol"], 3), d["play"])
                if sig_ in seen:
                    continue
                seen.add(sig_)
                stream = streamed.from_packet(d) if not d.get("file") else None
                local = self._stream_copy(stream) if stream else self._track(d["file"])
                if local is None:  # still on its way: this deck joins when its track is here
                    continue
                last_pos, changed = self.moved.get(d["deck"], (None, now))
                if last_pos is None or abs(d["pos"] - last_pos) > 1e-3:
                    changed = now
                self.moved[d["deck"]] = (d["pos"], changed)
                playing = bool(d["play"]) and now - changed < FROZEN_S
                decks[d["deck"]] = Deck(
                    d["deck"],
                    local,
                    d["pos"],
                    d["len"],
                    playing,
                    d["bpm"],
                    d["bpm0"],
                    d["vol"],
                    at,
                    title=d.get("title", ""),
                    artist=d.get("artist", ""),
                    stream=stream.service if stream else "",
                    copy=self.fetcher.status(stream) if stream and self.fetcher else "",
                    phase=d["phase"] if d.get("phase") is not None else self._link_phase(d, now, at),
                )
            self.decks = decks

    def _stream_copy(self, s: streamed.Stream) -> str | None:
        """A track the DJ laptop streams (no file there, e.g. Spotify): a copy of the same recording, fetched here,
        as for djay on this computer (streamed.py), when switched on here (Settings ▸ Integrations)."""
        if self.fetcher is None:
            self.fetcher = False
            if streamed.enabled():
                try:
                    self.fetcher = streamed.Fetcher()
                except ImportError:
                    print("  streamed tracks stay dark: yt-dlp isn't installed (Settings ▸ General ▸ Optional packs)")
        if not self.fetcher:
            if s.id not in self.dark:
                self.dark.add(s.id)
                why = "switched off (Settings ▸ Integrations ▸ Streamed tracks)" if self.fetcher is False else ""
                print(f"  {s.name} streams from {s.service.title()}: dark{', ' + why if why else ''}", flush=True)
            return None
        return self.fetcher.file(s) or None

    def _link_phase(self, d: dict, now: float, at: float) -> float | None:
        """A deck the DJ laptop says is synced to Ableton Link ("sync"), without a phase of its own: Link is a
        session on the network, so this computer joins it and reads the beat itself (Amadeus Link carries no
        Link code). The phase at `at`, the moment of the packet; None until joined, or when the tempos differ
        (another session, or not synced after all)."""
        if not d.get("sync") or not d.get("play") or self.ableton is False:
            return None
        if self.ableton is None:  # joining takes a moment: not in the way of the packets
            self.ableton = "joining"
            threading.Thread(target=self._join_ableton, daemon=True).start()
            return None
        if self.ableton == "joining":
            return None
        c, bpm = self.ableton, d["bpm"]
        if not c.peers or abs(c.tempo - bpm) >= 0.1:
            return None
        return (c.phase() - (now - at) * bpm / 60.0) % 1.0

    def _join_ableton(self):
        try:
            from amadeus.show.sources.ableton import LinkClock

            self.ableton = LinkClock()
            print("  ⇄ joined Ableton Link: synced decks follow its beat", flush=True)
        except ImportError:
            self.ableton = False
            print("  a deck on SYNC: no Ableton Link here (pip install aalink): positions without it", flush=True)

    def alive(self) -> bool:
        return self.connected and time.monotonic() - self.last < STALE_S

    # ---------------------------------------------------------------- tracks

    def _track(self, remote: str) -> str | None:
        """The local copy of a track the DJ laptop plays, or None while it is being fetched."""
        if not remote:
            return None
        if remote in self.local:
            return self.local[remote]
        if remote not in self.transfers:
            self.transfers[remote] = "running"
            threading.Thread(target=self._fetch, args=(remote,), daemon=True).start()
        return None

    def _fetch(self, remote: str):
        t0 = time.monotonic()
        try:
            with socket.create_connection((self.host, self.port), timeout=10) as s:
                _send(s, {"file": remote, "session": self.session, "auth": _h(self.key, "file", remote).hex()})
                buf = b""
                while b"\n" not in buf:
                    chunk = s.recv(65536)
                    if not chunk:
                        raise OSError("closed")
                    buf += chunk
                line, rest = buf.split(b"\n", 1)
                head = json.loads(line)
                if not head.get("ok"):
                    raise OSError(head.get("error", "refused"))
                name = Path(remote.replace("\\", "/")).name
                folder = self.cache / head["sha256"][:16]
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / name
                if not (path.exists() and path.stat().st_size == head["size"]):
                    h = hashlib.sha256(rest)
                    tmp = path.with_suffix(path.suffix + ".part")
                    with open(tmp, "wb") as f:
                        f.write(rest)
                        got = len(rest)
                        while got < head["size"]:
                            chunk = s.recv(1 << 20)
                            if not chunk:
                                raise OSError("connection closed during the transfer")
                            f.write(chunk)
                            h.update(chunk)
                            got += len(chunk)
                    if h.hexdigest() != head["sha256"]:
                        tmp.unlink(missing_ok=True)
                        raise OSError("checksum mismatch")
                    tmp.replace(path)
                    os.utime(path, (head["mtime"], head["mtime"]))  # a stable analysis cache key
                self.local[remote] = str(path)
                self.transfers[remote] = "done"
                print(
                    f"  ↓ {name}: {head['size'] / 1e6:.1f} MB from {self.name} in {time.monotonic() - t0:.1f} s",
                    flush=True,
                )
        except (OSError, ValueError, KeyError) as e:
            self.transfers[remote] = f"failed: {e}"
            print(f"  ⚠ could not fetch {remote}: {e}", flush=True)

    def status(self) -> dict:
        """For the visualiser / app: who, how well, what is being fetched."""
        return {
            "name": self.name,
            "up": self.alive(),
            "offset_ms": round((self.offset or 0) * 1000, 1),
            "jitter_ms": round(self.jitter_ms, 1),
            "lost": self.lost,
            "packets": self.packets,
            "fetching": [Path(r.replace("\\", "/")).name for r, st in self.transfers.items() if st == "running"],
        }

    def health(self) -> str:
        off = f"{self.offset * 1000:+.1f} ms" if self.offset is not None else "–"
        return (
            f"link {self.name}: {'up' if self.alive() else 'DOWN'}, offset {off}, jitter {self.jitter_ms:.1f} ms, "
            f"lost {self.lost}/{self.packets + self.lost}"
        )
