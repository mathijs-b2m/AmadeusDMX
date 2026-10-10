"""The director: picks the section and a layered look for every phrase of a track.

`OpenAIDirector` asks the OpenAI Decisions API (or `OllamaDirector` a local model); `RuleDirector` is a
deterministic fallback that needs no network and no API key. All of them produce the same `Decision`
objects, so the engine doesn't care which one ran.
"""

from decisive.director.decision import Decision, load_plan, save_plan
from decisive.director.llm import MODEL, PROMPT_VERSION, OllamaDirector, OpenAIDirector
from decisive.director.plan import Cancelled, direct
from decisive.director.rules import RuleDirector

__all__ = [
    "MODEL",
    "PROMPT_VERSION",
    "Cancelled",
    "Decision",
    "OllamaDirector",
    "OpenAIDirector",
    "RuleDirector",
    "direct",
    "load_plan",
    "save_plan",
]
