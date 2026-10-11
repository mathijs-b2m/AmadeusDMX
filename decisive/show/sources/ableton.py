"""Ableton Link: the shared beat clock of DJ software that syncs to it (djay, Serato, Traktor, rekordbox, …).

Link carries tempo and beat phase, never which track or where in it: a source uses it to sharpen a position it
already roughly knows (see base.PhaseLock). Needs aalink (pip install aalink).
"""

from __future__ import annotations

import asyncio
import threading


class LinkClock:
    """Joins the Link session and reads its beat. aalink wants an asyncio loop: it gets its own thread."""

    def __init__(self):
        import aalink

        self.link = None
        ready = threading.Event()

        def run():
            loop = asyncio.new_event_loop()

            async def start():
                self.link = aalink.Link(120)  # our tempo never counts: we only listen
                self.link.enabled = True
                ready.set()

            loop.run_until_complete(start())
            loop.run_forever()

        threading.Thread(target=run, daemon=True).start()
        ready.wait(5)

    @property
    def peers(self) -> int:
        return self.link.num_peers if self.link else 0

    @property
    def tempo(self) -> float:
        return self.link.tempo if self.link else 0.0

    def phase(self) -> float:
        """Beat phase right now, 0..1."""
        return self.link.beat % 1.0 if self.link else 0.0
