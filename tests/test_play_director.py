"""Playing a track with a set whose decision model is the OpenAI director, without a key: the rules light it (as in
a live show), instead of the engine stopping. A --director openai on the command line still asks for the key."""

from argparse import Namespace

import pytest

from amadeus import pipeline
from amadeus.cli import show as cli


class Stop(Exception):
    pass


class Show:
    def load(self):
        return {"director": "openai"}


def _director(monkeypatch, tmp_path, director="auto"):
    chosen = []

    def pick(name, *a, **k):
        chosen.append(name)
        raise Stop

    monkeypatch.setattr(pipeline, "pick_director", pick)
    args = Namespace(cmd="play", director=director, show=Show(), wav=tmp_path / "t.wav", redo=False, tempo=None)
    with pytest.raises(Stop):
        cli.direct_or_play(args)
    return chosen[0]


def test_a_set_on_openai_without_a_key_plays_with_the_rules(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _director(monkeypatch, tmp_path) == "rules"


def test_with_a_key_the_set_keeps_its_ai_director(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    assert _director(monkeypatch, tmp_path) == "openai"


def test_an_ai_plan_made_before_still_plays_without_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pipeline, "plan_path", lambda *a, **k: tmp_path)  # exists
    assert _director(monkeypatch, tmp_path) == "openai"


def test_the_command_line_choice_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _director(monkeypatch, tmp_path, director="openai") == "openai"
