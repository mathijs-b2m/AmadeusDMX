"""A light show per track: analysis and plan built in the background the first time a track appears."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from decisive.director.style import SetGenre
from decisive.engine import Engine


class TrackShows:
    """Analysis + plan + engine per track, built in the background the first time a track appears."""

    def __init__(self, rig: dict, director: str, cache: Path, real_output: bool = False):
        self.rig, self.director, self.cache = rig, director, cache
        self.real_output = real_output
        self.shows: dict[str, tuple] = {}  # file → (analysis, plan, engine, director used)
        self.pending: set[str] = set()
        self.status: dict[str, dict] = {}  # file → progress per step, for the visualiser
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        self.set_genre = SetGenre()  # the set's genre: tracks of a genre share a house style

    def _style_genre(self, file: str):
        return lambda a: self.set_genre.genre_for(file, a.genre, a.genre_source)

    def set_director(self, director: str):
        """Switch decision model: every known track gets a plan from the new one (cached plans are instant)."""
        if director == self.director:
            return
        print(f"  ⇄ decision model: {self.director} → {director}")
        self.director = director
        with self.lock:  # busy tracks pick up the change themselves (their job notices and restarts)
            files = [f for f in self.shows if f not in self.pending]
            for f in files:
                self.pending.add(f)
        for f in files:
            self.pool.submit(self._build, f, False)

    def get(self, file: str):
        with self.lock:
            show = self.shows.get(file)
            if show is None and file not in self.pending:
                self.pending.add(file)
                self.pool.submit(self._build, file)
        return show

    def progress(self, file: str) -> dict:
        """What is ready for a track: analysis, instruments, AI plan, and which plan the lights use."""
        st = dict(self.status.get(file, {}))
        show = self.shows.get(file)
        st["lights"] = show[3] if show else None
        if "since" in st:
            st["elapsed"] = round(time.monotonic() - st.pop("since"))
        return st

    def _step(self, file: str, **kw):
        st = self.status.setdefault(file, {})
        if kw.get("stems") == "running" or kw.get("ai") == "running":
            st["since"] = time.monotonic()
        st.update(kw)

    def _build(self, file: str, first: bool = True):
        from decisive.director import Cancelled
        from decisive.pipeline import get_plan

        try:
            if not Path(file).exists():
                print(f"  ⚠ {file} not found on disk")
                return
            if first:
                self._step(file, analysis="running")
                style = self._style_genre(file)
                a, plan = get_plan(Path(file), "rules", False, rig=self.rig, style_genre=style)  # immediately usable
                self._step(file, analysis="done")
                self._install(file, a, plan, "rules")
                if self._separate(file):  # the lights run meanwhile; then the show gets the synth notes
                    a, plan = get_plan(Path(file), "rules", False, rig=self.rig, style_genre=style)
                    self._install(file, a, plan, "rules")
            done = "rules" if first else None
            while self.director != done:  # (re)build until the plan of the CURRENT model is installed
                director = self.director
                if director != "rules":
                    self._step(file, ai="running", ai_done=0, ai_total=0, ai_model=director)
                try:
                    a, plan = get_plan(
                        Path(file),
                        director,
                        False,
                        cancel=lambda d=director: self.director != d,
                        rig=self.rig,
                        style_genre=self._style_genre(file),
                        progress=lambda k, n, f=file: self.status[f].update(ai_done=k, ai_total=n),
                    )
                except Cancelled:
                    print(f"  ✗ {Path(file).name}: stopped {director} (decision model switched)")
                    continue
                if director == self.director:
                    self._install(file, a, plan, director)
                    if director != "rules":
                        self._step(file, ai="done", ai_done=len(plan), ai_total=len(plan))
                done = director
        except BaseException as e:  # noqa: BLE001 - a bad track must never stop the show
            print(f"  ⚠ could not prepare {Path(file).name}: {e}")
        finally:
            with self.lock:
                self.pending.discard(file)

    def _separate(self, file: str) -> bool:
        """Separate the instruments in a background process (own memory, the light loop isn't disturbed)
        before the AI plans the track. True if new notes became available."""
        from decisive.audio import stems as stemlib
        from decisive.audio.analysis import readable_audio

        if not stemlib.available():
            self._step(file, stems="n/a")
            return False
        src = readable_audio(Path(file), self.cache)
        if stemlib.load_notes(src) is not None:
            self._step(file, stems="done")
            return False
        self._step(file, stems="running")
        name = Path(file).name
        t0 = time.monotonic()
        other = stemlib.running(src)
        if other:  # already being separated (e.g. by an earlier session): wait for it
            print(f"  ⧗ {name}: instruments are already being separated (pid {other}), waiting …", flush=True)
            proc = None
            while stemlib.running(src):
                time.sleep(1.0)
        else:
            print(f"  ⧗ {name}: separating instruments in the background (the show already runs) …", flush=True)
            proc = stemlib.start_background(src)
            while proc.poll() is None:
                time.sleep(1.0)
        if stemlib.load_notes(src) is None:
            err = (
                (proc.stderr.read() or b"").decode(errors="replace").strip().splitlines()[-1:]
                if proc is not None and proc.stderr
                else []
            )
            print(f"  ⚠ {name}: separation failed ({err[0] if err else 'no output'}); continuing without it")
            self._step(file, stems="failed")
            return False
        print(f"  ✓ {name}: instruments separated in {time.monotonic() - t0:.0f} s")
        self._step(file, stems="done", stems_s=round(time.monotonic() - t0))
        return True

    def _install(self, file, a, plan, director):
        engine = Engine(a, plan, self.rig, real_output=self.real_output)
        with self.lock:
            self.shows[file] = (a, plan, engine, director)
        print(f"  ✓ {Path(file).name}: {len(plan)} phrases, {a.bpm:.1f} BPM ({director})")
