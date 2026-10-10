"""Directing a whole track: one decision per phrase, from any director."""

from __future__ import annotations

from decisive.audio.model import DROP_THRESHOLD, Analysis
from decisive.director.decision import Decision, fmt_time


class Cancelled(Exception):
    """Raised when a plan is no longer wanted (e.g. the decision model was switched)."""


def direct(a: Analysis, director, verbose: bool = True, cancel=None, progress=None) -> list[Decision]:
    """`progress(done, total)` is called after every phrase (live mode shows it in the visualiser)."""
    history: list[Decision] = []
    for i in range(len(a.phrases)):
        if cancel and cancel():
            raise Cancelled()
        d = director.decide(a, i, history)
        d.drop_score = a.phrases[i].drop_score
        history.append(d)
        if progress:
            progress(i + 1, len(a.phrases))
        if verbose:
            mark = " ⚡" if d.drop_score >= DROP_THRESHOLD else ""
            print(f"  {fmt_time(d.start):>6}  {d.section:<9} {d.summary()} int={d.intensity} [{d.source}]{mark}")
    return history
