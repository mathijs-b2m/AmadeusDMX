"""A key OpenAI refuses: the show goes on with the rules, the apps get a warning, and no rule plan passes as an AI plan."""

from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from amadeus import aikey
from amadeus.director.llm import KeyRefused, OpenAIDirector


def error(cls, status, code):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/x"))
    return cls("refused", response=response, body={"code": code})


EXPIRED = error(openai.AuthenticationError, 401, "invalid_api_key")
NO_CREDIT = error(openai.RateLimitError, 429, "insufficient_quota")
BUSY = error(openai.RateLimitError, 429, "rate_limit_exceeded")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(aikey, "_problem", None)
    monkeypatch.setattr(aikey, "_checked", False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_only_errors_about_the_key_count():
    assert aikey.classify(EXPIRED) == aikey.REJECTED
    assert aikey.classify(NO_CREDIT) == aikey.NO_CREDIT
    assert aikey.classify(BUSY) is None
    assert aikey.classify(TimeoutError()) is None


def test_note_keeps_the_warning_for_the_feed():
    assert not aikey.note(BUSY) and aikey.problem() is None
    assert aikey.note(EXPIRED) and aikey.problem() == aikey.REJECTED


def models(monkeypatch, result):
    calls = []

    def listing():
        calls.append(1)
        if isinstance(result, Exception):
            raise result

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(models=SimpleNamespace(list=listing)))
    return calls


def test_check_finds_a_refused_key_and_asks_once(monkeypatch):
    calls = models(monkeypatch, EXPIRED)
    assert aikey.check() == aikey.REJECTED
    assert aikey.check() == aikey.REJECTED
    assert len(calls) == 1


def test_check_without_a_network_warns_of_nothing_and_asks_again(monkeypatch):
    calls = models(monkeypatch, ConnectionError())
    assert aikey.check() is None
    assert aikey.check() is None
    assert len(calls) == 2


def test_check_without_a_key_asks_nothing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    assert aikey.check() is None and models(monkeypatch, EXPIRED) == []


def test_stood_in_needs_a_refused_key_and_a_rule_phrase():
    rules, ai = SimpleNamespace(source="rules+guard"), SimpleNamespace(source="openai+hold")
    assert not aikey.stood_in([rules])  # no refused key: the network failed, or the rules were chosen
    aikey.note(EXPIRED)
    assert aikey.stood_in([ai, rules])
    assert not aikey.stood_in([ai])  # a cached AI plan keeps playing


def director(tmp_path: Path, answer):
    d = OpenAIDirector.__new__(OpenAIDirector)
    d.client = SimpleNamespace(decisions=SimpleNamespace(create=answer))
    d.model, d.questions, d.timings = "m", [], []
    d.cache, d.cache_file = {}, tmp_path / "cache.json"
    return d


def test_a_refused_key_is_asked_once_not_for_every_phrase(tmp_path):
    calls = []

    def answer(**kw):
        calls.append(kw)
        raise EXPIRED

    d = director(tmp_path, answer)
    with pytest.raises(openai.AuthenticationError):
        d._ask("phrase 1")
    aikey.note(EXPIRED)
    with pytest.raises(KeyRefused):
        d._ask("phrase 2")
    assert len(calls) == 1


def plan_with(monkeypatch, tmp_path, decisions):
    from amadeus import pipeline

    saved = []
    a = SimpleNamespace(genre="house", style="", phrases=[])
    monkeypatch.setattr(pipeline, "analyze", lambda *args, **kw: a)
    monkeypatch.setattr(pipeline, "theme_of", lambda wav: None)
    monkeypatch.setattr(pipeline, "_sections_key", lambda a: "")
    monkeypatch.setattr(pipeline, "plan_path", lambda *args: tmp_path / "plan.json")
    monkeypatch.setattr(pipeline, "OpenAIDirector", lambda *args, **kw: None)
    monkeypatch.setattr(pipeline, "direct", lambda *args, **kw: decisions)
    monkeypatch.setattr(pipeline, "save_plan", lambda plan, path: saved.append(path))
    assert pipeline.get_plan(Path("x.wav"), "openai", False)[1] == decisions
    return saved


def test_rules_standing_in_are_not_kept_as_the_ai_plan(monkeypatch, tmp_path):
    aikey.note(EXPIRED)
    assert plan_with(monkeypatch, tmp_path, [SimpleNamespace(source="rules")]) == []


def test_an_ai_plan_is_kept(monkeypatch, tmp_path):
    assert plan_with(monkeypatch, tmp_path, [SimpleNamespace(source="openai")]) != []


def build(monkeypatch, source):
    from amadeus import pipeline
    from amadeus.rig.loader import load_rig
    from amadeus.show import tracks

    monkeypatch.setattr(pipeline, "get_plan", lambda *args, **kw: ("a", [SimpleNamespace(source=source)]))
    shows = tracks.TrackShows(load_rig("tests/sets/small.json"), "openai", Path("."))
    monkeypatch.setattr(shows, "_install", lambda f, a, p, d: shows.shows.__setitem__(f, (a, p, None, d)))
    shows.shows[__file__] = ("a", [], None, "rules")
    shows._build(__file__, first=False)
    return shows.progress(__file__)


def test_a_track_the_rules_stood_in_for_says_so_on_its_deck(monkeypatch):
    aikey.note(EXPIRED)
    st = build(monkeypatch, "rules")
    assert st["lights"] == "rules" and st["ai"] == "failed"


def test_a_cached_ai_plan_stays_an_ai_plan_with_a_refused_key(monkeypatch):
    aikey.note(EXPIRED)
    st = build(monkeypatch, "openai")
    assert st["lights"] == "openai" and st["ai"] == "done"
