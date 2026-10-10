"""The engine: turns (time, decisions, analysis) into fixture states and DMX."""

from decisive.engine.engine import Engine
from decisive.engine.state import NUMERIC, State

__all__ = ["NUMERIC", "Engine", "State"]
