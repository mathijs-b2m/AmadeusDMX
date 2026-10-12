"""Recognise a fixture from a photo: of its product label (the sticker on the back or bottom), or of
the fixture itself (the shape, lens and any logo).

Two ways, both ending in fixtures from the catalogue (never a free-form guess):

- OpenAI Decisions API (needs OPENAI_API_KEY): first what the photo shows (label or fixture), the kind
  of fixture, beam/spot/wash and the brand, then "which model?" among the library fixtures that fit.
  A label usually settles it; from the looks alone it is a best guess with runners-up.
- Local (Ollama vision model, e.g. gemma4): the model reads brand and model off the label, then the
  text is looked up with the normal catalogue search.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from collections import defaultdict

from amadeus import paths
from amadeus.library import catalog
from amadeus.library.catalog import _typed
from amadeus.library.ofl import _tokens

OLLAMA = paths.ollama_host()
NONE = "__none__"


def _brand_key(name: str) -> str:
    return "".join(_tokens(name))


def _brands() -> dict[str, list[dict]]:
    """Normalised brand → its catalogue entries ("beamZ" and "BeamZ" are one brand)."""
    out: dict[str, list[dict]] = defaultdict(list)
    for c in catalog._candidates():
        out[_brand_key(c["manufacturer"])].append(c)
    return out


def _display(entries: list[dict]) -> str:
    names = [c["manufacturer"] for c in entries]
    # prefer the spelling with capitals and spaces ("American DJ" over "american_dj")
    return max(set(names), key=lambda n: (names.count(n), any(ch.isupper() for ch in n), " " in n))


def engines() -> list[str]:
    out = []
    if os.environ.get("OPENAI_API_KEY"):
        out.append("openai")
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=2) as r:
            models = [
                m["name"] for m in json.loads(r.read()).get("models", []) if "vision" in m.get("capabilities", [])
            ]
        models.sort(key=lambda m: (not m.startswith("gemma"), "mlx" in m, m))
        out += [f"ollama:{m}" for m in models[:1]]
    except OSError:
        pass
    return out


# ------------------------------------------------------------------ OpenAI Decisions API

TYPES = {
    "moving head": "Moving head: a head that pans and tilts on a yoke above a base",
    "scanner": "Scanner: a fixed body with a moving mirror",
    "par": "PAR / spot light / wash: a fixed light, usually a can or flat housing with LEDs on a bracket",
    "led bar": "LED bar or batten, a bar/kit of several small lights, or a pixel bar/matrix",
    "strobe": "Strobe or blinder",
    "laser": "Laser",
    "effect": "Effect light (derby, moonflower, multi-beam, UV, …)",
    "smoke": "Smoke machine, hazer or fog machine",
    "other": "Something else",
}
NEAR = {
    "par": {"par", "led bar"},
    "led bar": {"led bar", "par"},
    "moving head": {"moving head", "scanner"},
    "scanner": {"scanner", "moving head"},
    "strobe": {"strobe", "par"},
    "effect": {"effect", "laser"},
}
LOOKS = {
    "beam": "Beam: a narrow, very bright pencil beam from a small lens (often with prism)",
    "spot": "Spot: a projector with gobos and colour wheel, a mid-sized lens",
    "wash": "Wash: a wide, soft light, often many LEDs or a large frosted/Fresnel lens, often zoom",
    "hybrid": "Hybrid / profile: beam, spot and wash in one, often a large lens and shutters",
    "": "Not a moving head, or cannot tell",
}
CHUNK = 350
DIRECT = 0.9  # open the fixture straight away at this probability (only when a label was read)


def _ask(client, image_url: str, questions: list[dict]) -> dict[str, dict]:
    from amadeus.director import MODEL

    d = client.decisions.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "A phone photo taken while setting up stage lighting: the product label "
                        "(type plate) of a fixture, and/or the fixture itself.",
                    },
                    {"type": "input_image", "image_url": image_url, "detail": "high"},
                ],
            }
        ],
        questions=questions,
    )
    return {a.name: a.model_dump() for a in d.answers}


def _ranked(ans: dict | None) -> list[tuple[str, float]]:
    if not ans or ans.get("type") != "choice":
        return []
    probs = [(p["value"], p["probability"]) for p in ans.get("probabilities", [])]
    return sorted(probs, key=lambda x: -x[1]) or [(ans["choice"], ans.get("confidence", 0.0))]


def _choice(name, instructions, choices: dict[str, str]) -> dict:
    return {
        "name": name,
        "type": "choice",
        "instructions": instructions,
        "choices": [{"value": v, "description": d} for v, d in choices.items()],
    }


def _describe(c: dict) -> str:
    kind = c["type"] + (f", {c['look']}" if c.get("look") else "")
    return f"{c['manufacturer']} {c['model']} ({kind})"


VISION_MODEL = "gpt-6-luna"
VISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["photo", "brand", "model", "type", "look", "visible_text", "alternatives", "confidence", "reasoning"],
    "properties": {
        "photo": {
            "type": "string",
            "enum": ["label", "fixture", "both", "other"],
            "description": "label: a type plate with readable text; fixture: the fixture without a readable "
            "model name; both: fixture with a readable name; other: no fixture or label",
        },
        "brand": {"type": "string", "description": "manufacturer, '' if unknown"},
        "model": {"type": "string", "description": "exact model name as the manufacturer writes it, '' if unknown"},
        "type": {"type": "string", "enum": list(TYPES)},
        "look": {"type": "string", "enum": list(LOOKS), "description": "for moving heads"},
        "visible_text": {"type": "string", "description": "all text, logos, badges and numbers you can see"},
        "alternatives": {
            "type": "array",
            "items": {"type": "string"},
            "description": "up to 4 other 'Brand Model' it could be, most likely first",
        },
        "confidence": {"type": "number", "description": "0..1 that brand and model are exactly right"},
        "reasoning": {"type": "string", "description": "one short sentence"},
    },
}


def _vision(client, image_url: str) -> dict:
    """Free look at the photo by a vision model: what it is, from the label or from what the product looks like."""
    r = client.responses.create(
        model=VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Identify this stage lighting fixture: brand and exact model. The photo shows its "
                        "product label / type plate, or the fixture itself (then use the housing shape, "
                        "lens, LED layout, base, display and logo, and what you know these products "
                        "look like). First look closely for any logo, badge or number on the head, yoke "
                        "and base (e.g. a small model number badge on the base) and use it. "
                        "Common DJ brands: beamZ, Ayra, Showtec, Chauvet, ADJ, Cameo, "
                        "Eurolite, Stairville, Martin, Robe, Clay Paky, Elation, Fun Generation.",
                    },
                    {"type": "input_image", "image_url": image_url, "detail": "high"},
                ],
            }
        ],
        text={"format": {"type": "json_schema", "name": "fixture", "schema": VISION_SCHEMA, "strict": True}},
    )
    return json.loads(r.output_text)


def identify_openai(image_url: str) -> dict:
    """A vision model (gpt-6-astra) says what it sees; the Decisions API then picks the matching library
    entry among the closest candidates, with the photo. Falls back to Decisions-only if that fails."""
    from openai import OpenAI

    client = OpenAI()
    try:
        seen = _vision(client, image_url)
    except Exception as e:  # noqa: BLE001
        out = identify_decisions(image_url)
        out["note"] = (out["note"] + f" ({VISION_MODEL} failed: {e.__class__.__name__})").strip()
        return out
    out = {
        "engine": f"openai:{VISION_MODEL}",
        "photo": seen["photo"],
        "type": seen["type"],
        "look": seen["look"] or None,
        "read": {
            "brand": seen["brand"],
            "model": seen["model"],
            "text": seen["visible_text"],
            "reasoning": seen["reasoning"],
            "confidence": seen["confidence"],
        },
        "brand": {"name": seen["brand"], "probability": round(seen["confidence"], 3)} if seen["brand"] else None,
        "matches": [],
        "note": "",
    }
    if seen["photo"] == "other":
        out["note"] = "No fixture or label recognised in this photo."
        return out

    # Candidates: library search for the guess and each alternative, plus the brand's other fixtures.
    brands = _brands()
    pool: dict[str, dict] = {}
    for guess in [f"{seen['brand']} {seen['model']}", *seen["alternatives"][:4]]:
        for c in catalog.search(guess, 12):
            pool.setdefault(c["key"], _typed(c))
    bk = _brand_key(seen["brand"])
    if bk:
        root = _tokens(seen["brand"])[0]
        for k, entries in brands.items():
            if k == bk or k.startswith(root):
                for c in entries:
                    if c["type"] in NEAR.get(seen["type"], {seen["type"]}):
                        pool.setdefault(c["key"], c)
    cands = list(pool.values())[:CHUNK]
    out["candidates"] = len(cands)
    if not cands:
        out["note"] = f"Looks like {seen['brand']} {seen['model']}, but that is not in the fixture libraries."
        return out
    # The Decisions API reads the photo itself; it is not told the vision model's reading (a misread name,
    # e.g. "GBC" for "ERO", would otherwise steer it away from the right entry).
    how = (
        "Read the brand and model name on the label or housing (logos may use stylised letters)."
        if seen["photo"] in ("label", "both")
        else "There is no readable model name: judge from the housing shape, lens, base, display and any logo or "
        "number on it, and from what you know these products look like."
    )
    a = _ask(
        client,
        image_url,
        [
            _choice(
                "model",
                f"Which of these fixtures is in the photo? {how} The list spells names the way the fixture "
                f"libraries do (spaces, dashes and capitals may differ). Choose 'none' if it is not in the list.",
                {**{c["key"]: _describe(c) for c in cands}, NONE: "None of these / not in the list"},
            )
        ],
    )
    by_key = {c["key"]: c for c in cands}
    # From the looks alone the pick among candidates says little about being right overall: scale it by
    # how sure the vision model was.
    trust = 1.0 if seen["photo"] in ("label", "both") else max(0.05, min(1.0, seen["confidence"]))
    ranked_models = _ranked(a.get("model"))
    none_p = next((p for k, p in ranked_models if k == NONE), 0.0)
    out["matches"] = [
        dict(by_key[k], probability=round(p * trust, 3)) for k, p in ranked_models if k in by_key and p >= 0.02
    ][:5]
    out["direct"] = (
        bool(out["matches"]) and seen["photo"] in ("label", "both") and out["matches"][0]["probability"] >= DIRECT
    )
    if out["matches"] and (none_p >= 0.5 or out["matches"][0]["probability"] < 0.3):
        out["note"] = (
            f"Looks like {seen['brand']} {seen['model']}, which may not be in the fixture libraries; "
            f"closest entries below."
        )
    if not out["matches"]:
        out["note"] = f"Looks like {seen['brand']} {seen['model']}, but no library entry matches: search by name."
    elif seen["photo"] == "fixture" and not out["note"]:
        out["note"] = (
            "Recognised from the looks (no label): check it is really this model, or photograph the label to be sure."
        )
    return out


def identify_decisions(image_url: str) -> dict:
    """Step 1: what the photo shows, fixture type, beam look and brand (one call). Step 2: the model among
    the candidates step 1 leaves (several calls in parallel when no brand narrows it down, then a final)."""
    from concurrent.futures import ThreadPoolExecutor

    from openai import OpenAI

    client = OpenAI()
    brands = _brands()
    a = _ask(
        client,
        image_url,
        [
            _choice(
                "photo",
                "What does the photo show?",
                {
                    "label": "A product label / type plate with readable text (brand and/or model name)",
                    "fixture": "The fixture itself; no readable model name (maybe a logo)",
                    "both": "The fixture with a readable model name or label on it",
                    "other": "No lighting fixture or label",
                },
            ),
            _choice(
                "type",
                "Which kind of lighting fixture is it? Judge from the label text (e.g. 'moving head', "
                "'LED PAR') or from the shape.",
                TYPES,
            ),
            _choice(
                "look",
                "If it is a moving head: which kind? From the name (e.g. 'Beam', 'Spot', 'Wash') or the lens and head.",
                LOOKS,
            ),
            _choice(
                "brand",
                "Which manufacturer made it? Read the brand name or logo (on the label, housing, base or "
                "display). Spelling and capitals may differ slightly from the list. Do not guess a brand "
                "from the shape alone: pick 'none' when no brand name or logo is visible.",
                {
                    **{k: _display(v) for k, v in sorted(brands.items())},
                    NONE: "No brand name or logo is visible, or it is not in this list",
                },
            ),
        ],
    )
    photo = (_ranked(a.get("photo")) or [("fixture", 0)])[0][0]
    ftype, type_p = (_ranked(a.get("type")) or [("other", 0)])[0]
    look, look_p = (_ranked(a.get("look")) or [("", 0)])[0]
    ranked = [(b, p) for b, p in _ranked(a.get("brand")) if b != NONE and b in brands]
    brand, brand_p = ranked[0] if ranked and ranked[0][1] >= 0.3 else (None, 0.0)
    out = {
        "engine": "openai",
        "photo": photo,
        "type": ftype,
        "look": look or None,
        "brand": {"name": _display(brands[brand]), "probability": round(brand_p, 3)} if brand else None,
        "matches": [],
        "note": "",
    }
    if photo == "other":
        out["note"] = "No fixture or label recognised in this photo."
        return out

    if brand:
        # The libraries split some brands ("Chauvet", "Chauvet DJ", "Chauvet Professional"): offer the models
        # of every brand starting with the same word, plus any runner-up brand the first answer considered.
        root = _tokens(_display(brands[brand]))[0]
        family = {k for k, v in brands.items() if _tokens(_display(v))[0] == root} | {b for b, p in ranked if p >= 0.05}
        pool = [c for k in sorted(family, key=lambda k: k != brand) for c in brands[k]]
        same = lambda c: c["type"] in NEAR.get(ftype, {ftype})
        pool.sort(key=lambda c: not same(c))  # matching type first if the brand has more than fit in one list
    else:
        if type_p < 0.5 or ftype == "other":
            out["note"] = "No brand visible and the kind of fixture is unclear: try a photo of the label."
            return out
        pool = [c for b in brands.values() for c in b if c["type"] in NEAR.get(ftype, {ftype})]
        if ftype == "moving head" and look and look_p >= 0.6:
            pool = [c for c in pool if c.get("look") in (look, "", "hybrid")]

    how = (
        "Read the model name/number on the label; the list spells it the way the fixture libraries do "
        "(spaces, dashes and capitals may differ). Article numbers alone are not model names."
        if photo in ("label", "both")
        else "There is no readable model name: judge from what you see (housing shape, lens size and number, "
        "LED layout, base, handles, display, logo) and what you know these products look like. If none "
        "is clearly it, choose 'none'."
    )
    question = lambda chunk: _choice(
        "model", f"Which fixture is this? {how}", {**{c["key"]: _describe(c) for c in chunk}, NONE: "None of these"}
    )
    chunks = [pool[i : i + CHUNK] for i in range(0, len(pool), CHUNK)][:6]  # at most ~2,100 candidates
    by_key = {c["key"]: c for c in pool}
    if len(chunks) > 1:  # round 1 per chunk in parallel, then a final among each chunk's best 3
        with ThreadPoolExecutor(len(chunks)) as ex:
            rounds = list(ex.map(lambda ch: _ask(client, image_url, [question(ch)]).get("model"), chunks))
        finalists = [by_key[k] for r in rounds for k, p in _ranked(r)[:3] if k in by_key and p >= 0.02]
        chunks = [finalists] if finalists else []
    ranked_models = _ranked(_ask(client, image_url, [question(chunks[0])]).get("model")) if chunks else []
    out["matches"] = [dict(by_key[k], probability=round(p, 3)) for k, p in ranked_models if k in by_key and p >= 0.02][
        :5
    ]
    out["candidates"] = len(pool)
    out["direct"] = bool(out["matches"]) and photo in ("label", "both") and out["matches"][0]["probability"] >= DIRECT
    if not out["matches"]:
        out["note"] = (
            f"{_display(brands[brand])} found, but not the model: search by name."
            if brand
            else "Could not tell which model this is from the looks: try a photo of the label."
        )
    elif photo == "fixture":
        out["note"] = (
            "Recognised from the looks only (no label): check that it is really this model, "
            "or take a photo of the label to be sure."
        )
    return out


# ------------------------------------------------------------------ local vision model


def identify_ollama(image_url: str, model: str) -> dict:
    b64 = image_url.split(",", 1)[1]
    body = {
        "model": model,
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "user",
                "images": [b64],
                "content": "This is the product label of a stage lighting fixture. Reply with JSON only: "
                '{"brand": "...", "model": "...", "text": "all text you can read"}. '
                'Use "" when something is not readable. The model is the product name/number '
                '(e.g. "Fuze75B Beam"), not the article number or the power rating.',
            }
        ],
    }
    req = urllib.request.Request(f"{OLLAMA}/api/chat", json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        content = json.loads(r.read())["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    read = json.loads(m.group(0)) if m else {}
    brand, name = str(read.get("brand", "")).strip(), str(read.get("model", "")).strip()
    matches = catalog.search(f"{brand} {name}", 5) if (brand or name) else []
    if brand and matches:  # keep the read brand's fixtures first
        bk = _brand_key(brand)
        matches.sort(key=lambda c: _brand_key(c["manufacturer"]) != bk)
    return {
        "engine": f"ollama:{model}",
        "read": {"brand": brand, "model": name, "text": read.get("text", "")},
        "brand": {"name": brand, "probability": None} if brand else None,
        "matches": matches,
        "note": "" if matches else "Nothing readable matched the libraries. Try a sharper photo, or search by name.",
    }


def identify(image_url: str, engine: str | None = None) -> dict:
    if not image_url.startswith("data:image/"):
        raise ValueError("expected an image as a data URL")
    base64.b64decode(image_url.split(",", 1)[1][:64] + "==")  # cheap sanity check
    available = engines()
    engine = engine or (available[0] if available else None)
    if engine is None:
        raise RuntimeError(
            "No image model available: set OPENAI_API_KEY, or install a vision model in Ollama "
            "(e.g. `ollama pull gemma4`)."
        )
    if engine == "openai":
        return identify_openai(image_url)
    return identify_ollama(image_url, engine.removeprefix("ollama:"))
