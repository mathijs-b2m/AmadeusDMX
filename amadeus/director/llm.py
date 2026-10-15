"""Language-model directors: the OpenAI Decisions API, or a local model through Ollama."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path

from amadeus.audio.model import DROP_THRESHOLD, Analysis
from amadeus.director.arc import apply_arc, laser_star, song_arc
from amadeus.director.decision import (
    FOG_NAMES,
    GROUP_NAMES,
    LASER_NAMES,
    LAYER_NAMES,
    SCREEN_NAMES,
    SPECIAL_NAMES,
    Decision,
)
from amadeus.director.prompt import build_prompt, questions_for, synth_riff
from amadeus.director.rules import PART_SECTION, PER_BEAT, RuleDirector
from amadeus.director.style import Style
from amadeus.director.vocabulary import SONG_SECTIONS

CLUB_SECTION = {"verse": "groove", "chorus": "groove", "bridge": "breakdown"}  # song parts in a club track

MODEL = "gpt-6-luna"


HOLD_CONFIDENCE = 0.35  # mean look confidence below this, in an unchanged section → keep the previous look


PROMPT_VERSION = 26


class OpenAIDirector:
    """Asks the Decisions API one multi-question request per phrase."""

    name = "openai"

    def __init__(
        self,
        cache_file: Path,
        model: str = MODEL,
        groups: list[dict] | None = None,
        lasers: list[dict] | None = None,
        screen: bool = False,
        style: Style | None = None,
        theme: str | None = None,
        fog: bool = False,
        outdoor: bool = False,
    ):
        from openai import OpenAI  # imported lazily so the rules mode works without a key

        self.client = OpenAI()
        self.model = model
        self.cache_file = cache_file
        self.cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        self.groups, self.lasers, self.screen, self.style, self.theme = groups, lasers, screen, style, theme
        self.fog, self.outdoor = fog, outdoor
        self.questions = questions_for(groups, lasers, screen, style, theme, fog)
        self.fallback = RuleDirector(groups, lasers, screen, style, theme, fog, outdoor)
        self.timings = []

    timings: list[float]

    def _ask(self, prompt: str) -> dict:
        key = hashlib.sha1(json.dumps([self.model, PROMPT_VERSION, prompt, self.questions]).encode()).hexdigest()
        if key not in self.cache:
            t0 = time.perf_counter()
            decision = self.client.decisions.create(model=self.model, input=prompt, questions=self.questions)
            self.timings.append(time.perf_counter() - t0)
            self.cache[key] = {a.name: a.model_dump() for a in decision.answers}
            self.cache_file.write_text(json.dumps(self.cache, indent=1))
        return self.cache[key]

    def decide(self, a: Analysis, i: int, history: list[Decision]) -> Decision:
        prompt = build_prompt(
            a, i, history, self.groups, self.lasers, self.screen, self.style, self.theme, self.fog, self.outdoor
        )
        d = self.fallback.decide(a, i, history)  # supplies any refused or failed answer
        d.prompt = prompt
        try:
            answers = self._ask(prompt)
        except Exception as e:  # network/API errors must never stop the show
            print(f"  phrase {i}: Decisions API failed ({e.__class__.__name__}: {e}); using rules")
            return d

        d.source = self.name
        names = [*LAYER_NAMES, *GROUP_NAMES, *LASER_NAMES, *SCREEN_NAMES, *SPECIAL_NAMES, *FOG_NAMES]
        for name in ["section", "palette", *names]:
            ans = answers.get(name)
            if ans and ans.get("type") == "choice":
                setattr(d, name, ans["choice"])
                d.confidence[name] = round(ans.get("confidence", 0.0), 3)
                d.probabilities[name] = {x["value"]: round(x["probability"], 3) for x in ans.get("probabilities", [])}
        ans = answers.get("intensity")
        if ans and ans.get("type") == "score":
            d.intensity = max(0, min(3, round(ans["score"])))
            d.confidence["intensity"] = round(ans.get("confidence", 0.0), 3)

        # Musical facts first: a drop the analysis is sure about stays a drop (the AI keeps its other choices).
        score = a.phrases[i].drop_score
        nxt = a.phrases[i + 1].drop_score if i + 1 < len(a.phrases) else 0.0
        guarded = False
        if score >= DROP_THRESHOLD and d.section != "drop":
            d.section, guarded = "drop", True
        if d.section == "drop" and score >= DROP_THRESHOLD and d.dynamics != "impact":
            d.dynamics, guarded = "impact", True
        if d.section == "drop":  # a drop is where everything energizes
            d.intensity = max(d.intensity, 2)
            if d.movement in ("still", "nod", "sweep"):
                d.movement, guarded = ("bounce" if d.head_light in ("flick", "beat") else "step_on_beat"), True
            if d.head_light == "off":
                d.head_light, guarded = "steady", True
            if d.par_accent == "none":
                d.par_accent, guarded = "pulse", True
        if nxt >= DROP_THRESHOLD and score < DROP_THRESHOLD:  # the phrase before a drop builds towards it
            if d.section != "buildup":
                d.section, guarded = "buildup", True
            if d.dynamics == "steady":
                d.dynamics, guarded = "rise", True
        # The song's form is a musical fact too: a song's parts are what its form says (a chorus is no drop), and
        # a club track has no verses.
        part = a.phrases[i].part
        if part and score < DROP_THRESHOLD and nxt < DROP_THRESHOLD and d.section != PART_SECTION.get(part, d.section):
            d.section, guarded = PART_SECTION[part], True
        elif not part and d.section in SONG_SECTIONS:
            d.section, guarded = CLUB_SECTION[d.section], True
        if part and d.section != "drop" and d.dynamics == "impact":
            d.dynamics, guarded = "steady", True  # in a song the impact curve is for its real drops only

        # High energy keeps moving: loud with a running kick (e.g. the phrases right after a drop).
        ph = a.phrases[i]
        if ph.loudness_pct >= 65 and ph.kick_ratio >= 0.8 and d.movement in ("still", "nod"):
            d.movement, guarded = ("step_on_beat" if d.formation in ("sync", "fan", "wave") else "circle"), True

        # A synth trigger without a riff has nothing to follow.
        if d.trigger == "synth" and synth_riff(a, ph) < 0.4:
            d.trigger, guarded = "eighths", True
        # No beat: percussive triggers have nothing to follow; no robotic note/vocal-following either.
        if ph.kick_ratio < 0.3 and d.trigger in ("kick", "backbeat", "hats", "lead"):
            d.trigger, guarded = "accents", True
        if d.movement == "follow_lead":  # retired option (old cached answers)
            d.movement, guarded = "sweep", True

        # Crisp beam by default: frost only as a rare soft moment in calm sections.
        recent_frost = any(h.beam_fx == "frost" for h in history[-3:])
        if d.beam_fx == "frost" and (d.section not in ("intro", "breakdown", "bridge", "outro") or recent_frost):
            d.beam_fx, guarded = "open", True

        # Variety: when a choice repeats too long, take the model's next most likely option instead.
        last = history[-1] if history else None

        def next_best(name: str, avoid: set) -> str | None:
            ranked = sorted(d.probabilities.get(name, {}).items(), key=lambda kv: -kv[1])
            return next((v for v, _ in ranked if v not in avoid), None)

        varied = ("movement", "formation", "head_light", "head_color")
        if self.groups and len(self.groups) > 1:
            varied += ("layer_split", "base_glow")
        for name in varied:
            recent = [getattr(h, name) for h in history[-2:]]
            if len(recent) == 2 and all(r == getattr(d, name) for r in recent):
                alt = next_best(name, {getattr(d, name)} | ({"off"} if name == "head_light" else set()))
                if alt:
                    setattr(d, name, alt)
                    guarded = True
        # Every drop gets its own character: differ from the previous drop in path, formation and beam.
        prev_drop = next((h for h in reversed(history) if h.section == "drop" and h.drop_score >= DROP_THRESHOLD), None)
        if d.section == "drop" and prev_drop and d.phrase != prev_drop.phrase + 1:
            for name in ("movement", "formation", "beam_fx"):
                if getattr(d, name) == getattr(prev_drop, name):
                    alt = next_best(name, {getattr(prev_drop, name), "still", "nod", "frost"})
                    if alt:
                        setattr(d, name, alt)
                        guarded = True
        if last and d.section in ("drop", "breakdown") and d.section != last.section and d.palette == last.palette:
            alt = next_best("palette", {last.palette})
            if alt:
                d.palette, guarded = alt, True

        # Lasers build too: never a static shape in a buildup or a drop.
        if self.lasers and d.laser_look != "off" and d.laser_move == "still" and d.section in ("buildup", "drop"):
            d.laser_move, guarded = next_best("laser_move", {"still"}) or "rotate", True

        # Groups: a drop needs the whole rig going; a split needs a real counter-movement; and the grouping
        # changes at least every two phrases (otherwise 60 heads look like one master with 59 slaves).
        if self.groups and len(self.groups) > 1:
            if d.section == "drop" and d.grouping == "solo":
                d.grouping, guarded = "split", True
            if d.grouping == "split" and d.movement2 == d.movement and d.formation2 == d.formation:
                d.movement2, guarded = ("sweep" if d.movement in PER_BEAT else "step_on_beat"), True
            recent = [h.grouping for h in history[-2:]]
            if len(recent) == 2 and all(r == d.grouping for r in recent):
                alt = next_best("grouping", {d.grouping} | ({"solo"} if d.section == "drop" else set()))
                if alt:
                    d.grouping, guarded = alt, True
            if d.grouping in ("split", "solo"):  # let every part of the rig lead now and then
                recent = [h.featured for h in history[-2:] if h.grouping in ("split", "solo")]
                if len(recent) == 2 and all(r == d.featured for r in recent):
                    alt = next_best("featured", {d.featured})
                    if alt:
                        d.featured, guarded = alt, True

        # A theme's special look is for key moments: at most two phrases in a row.
        if d.special != "off" and len(history) >= 2 and all(h.special == d.special for h in history[-2:]):
            d.special, guarded = "off", True

        # Hysteresis: a model that's unsure across the board, in an unchanged section, keeps the previous look.
        last = history[-1] if history else None
        look_conf = [d.confidence[n] for n in LAYER_NAMES if n in d.confidence]
        if last and d.section == last.section and look_conf and sum(look_conf) / len(look_conf) < HOLD_CONFIDENCE:
            for n in [*LAYER_NAMES, "palette"]:
                setattr(d, n, getattr(last, n))
            d.source = "openai+hold"
        arc = song_arc(a)[i]
        if laser_star(d, arc, self.lasers, next_best):
            guarded = True
        if apply_arc(d, arc, self.lasers, self.groups, next_best):  # the song's dramaturgy has the last word
            guarded = True
        if guarded:
            d.source += "+guard"
        return d


class OllamaDirector(OpenAIDirector):
    """A local decision model (e.g. nimble) via Ollama's Jev-style /v1/systemone endpoint.

    Same prompt, questions and safety nets as the Decisions API director; the endpoint also returns
    probabilities per option, so the variety rules work exactly as with OpenAI.
    """

    def __init__(
        self,
        cache_file: Path,
        model: str = "nimble",
        host: str | None = None,
        groups: list[dict] | None = None,
        lasers: list[dict] | None = None,
        screen: bool = False,
        style: Style | None = None,
        theme: str | None = None,
        fog: bool = False,
        outdoor: bool = False,
    ):
        from amadeus import paths

        self.model, self.host = model, host or paths.ollama_host()
        self.name = f"ollama-{model.replace(':', '-').replace('/', '-')}"
        self.cache_file = cache_file
        self.cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
        self.groups, self.lasers, self.screen, self.style, self.theme = groups, lasers, screen, style, theme
        self.fog, self.outdoor = fog, outdoor
        self.questions = questions_for(groups, lasers, screen, style, theme, fog)
        self.fallback = RuleDirector(groups, lasers, screen, style, theme, fog, outdoor)
        self.timings = []

    def _questions(self) -> dict:
        qs = {}
        for q in self.questions:
            if q["type"] == "choice":
                qs[q["name"]] = {
                    "type": "choice",
                    "instructions": q["instructions"],
                    "criteria": {c["value"]: c["description"] for c in q["choices"]},
                }
            else:
                qs[q["name"]] = {
                    "type": "score",
                    "instructions": q["instructions"],
                    "criteria": [lv["label"] for lv in q["levels"]],
                }
        return qs

    def _ask(self, prompt: str) -> dict:
        key = hashlib.sha1(json.dumps([self.model, PROMPT_VERSION, prompt, self.questions]).encode()).hexdigest()
        if key in self.cache:
            return self.cache[key]
        body = {"model": self.model, "state": {"music": prompt}, "questions": self._questions()}
        req = urllib.request.Request(
            f"{self.host}/v1/systemone", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.loads(r.read())
        self.timings.append(time.perf_counter() - t0)
        answers = {}  # same shape as the Decisions API answers, so decide() needs no changes
        for name, ans in raw.get("answers", {}).items():
            probs = [{"value": v, "probability": p} for v, p in ans.get("probabilities", {}).items()]
            if ans.get("type") == "choice":
                answers[name] = {
                    "type": "choice",
                    "name": name,
                    "choice": ans["choice"],
                    "probabilities": probs,
                    "confidence": ans.get("confidence", 0.0),
                }
            elif ans.get("type") == "score":
                answers[name] = {
                    "type": "score",
                    "name": name,
                    "score": float(ans["score"]),
                    "confidence": ans.get("confidence", 0.0),
                }
        self.cache[key] = answers
        self.cache_file.write_text(json.dumps(self.cache, indent=1))
        return answers
