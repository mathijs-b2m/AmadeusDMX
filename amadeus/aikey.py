"""Whether OpenAI still takes the key. A key that expired, or ran out of credit, never stops a show (the rules take
over), so without this nobody would know: the first refusal is kept here and the apps show `problem()` as a warning.
It lasts as long as this process, as the key does: the apps hand a new key to the next engine they start."""

from __future__ import annotations

import os

REJECTED = (
    "OpenAI no longer accepts your API key: it expired, was revoked or is wrong. Tracks without an AI plan get the "
    "rule-based show. Enter a new key in Settings › Director."
)
NO_CREDIT = (
    "Your OpenAI API key is out of credit. Tracks without an AI plan get the rule-based show. Add credit at OpenAI, "
    "or enter another key in Settings › Director."
)

_problem: str | None = None
_checked = False


def classify(e: BaseException) -> str | None:
    """The warning for this error from OpenAI, None when it says nothing about the key (a timeout, an outage)."""
    status = getattr(e, "status_code", None)
    if status == 401:
        return REJECTED
    if status == 429 and getattr(e, "code", None) == "insufficient_quota":
        return NO_CREDIT
    return None


def note(e: BaseException) -> bool:
    """Keep what this error says about the key. True if it was about the key."""
    global _problem
    found = classify(e)
    if found and found != _problem:
        _problem = found
        print(f"  ⚠ {found}", flush=True)
    return found is not None


def problem() -> str | None:
    return _problem


def stood_in(plan: list) -> bool:
    """Did the rules decide phrases of this plan because the key was refused?"""
    return _problem is not None and any(not d.source.startswith("openai") for d in plan)


def check() -> str | None:
    """Ask OpenAI once per process whether it takes the key (lists the models, nothing more), so the warning comes
    before the show needs the key. Not reachable: no warning, the key may be fine."""
    global _checked
    if not _checked and _problem is None and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI

        try:
            OpenAI(timeout=10, max_retries=0).models.list()
            _checked = True
        except Exception as e:  # noqa: BLE001 - only what it says about the key counts
            _checked = note(e)
    return _problem
