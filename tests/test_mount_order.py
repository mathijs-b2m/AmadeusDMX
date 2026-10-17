"""Auto-mount names in order: each model keeps its (symmetric) spots, and its fixtures take them in name order along
the rig, the hang sheet's order (top1 at the first place, top2 at the next), on every rig in tests/sets."""

import json
from collections import Counter
from pathlib import Path

import pytest

from amadeus.rig import automount, hangsheet, store

SETS = sorted(Path("tests/sets").glob("*.json"))


def mount(merged: dict) -> dict:
    places = automount.automount(merged, [f["id"] for f in merged["fixtures"]])
    for f in merged["fixtures"]:
        if f["id"] in places:
            for k in store.PLACEMENT_KEYS:
                f.pop(k, None)
            f.update(places[f["id"]])
    return merged


def in_sheet_order(merged: dict) -> list[str]:
    lay = hangsheet.layout(merged)
    return [r["id"] for st in lay["structures"] for r in st["fixtures"]] + [r["id"] for r in lay["floor"]]


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_names_count_along_the_rig_like_the_places(path):
    merged = mount(json.loads(path.read_text(encoding="utf-8")))
    key = automount.name_order(merged["fixtures"])
    model = {f["id"]: f["fixture"] for f in merged["fixtures"]}
    seen = in_sheet_order(merged)
    for m in set(model.values()):
        names = [i for i in seen if model[i] == m]
        assert names == sorted(names, key=key), m
    assert automount.in_order(merged) == {}  # already in order: nothing changes


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_in_order_puts_a_mixed_up_rig_right_without_moving_a_spot(path):
    merged = mount(json.loads(path.read_text(encoding="utf-8")))
    want = {f["id"]: {k: f[k] for k in store.PLACEMENT_KEYS if k in f} for f in merged["fixtures"]}
    by_model: dict[str, list[dict]] = {}
    for f in merged["fixtures"]:
        by_model.setdefault(f["fixture"], []).append(f)
    group = max(by_model.values(), key=len)
    if len(group) < 2:
        pytest.skip("no two fixtures of one model")
    a, b = group[0], group[-1]  # hung the other way about
    pa, pb = want[a["id"]], want[b["id"]]
    for f, p in ((a, pb), (b, pa)):
        for k in store.PLACEMENT_KEYS:
            f.pop(k, None)
        f.update(p)
    spots = Counter(json.dumps(p, sort_keys=True) for p in want.values())
    changed = automount.in_order(merged)
    assert changed == {a["id"]: pa, b["id"]: pb}
    after = {**{f["id"]: {k: f[k] for k in store.PLACEMENT_KEYS if k in f} for f in merged["fixtures"]}, **changed}
    assert Counter(json.dumps(p, sort_keys=True) for p in after.values()) == spots


def test_numbers_sort_as_numbers_and_name_families_keep_the_sets_order():
    key = automount.name_order([{"id": i} for i in ("top1", "back1", "top2", "top10", "back2")])
    assert sorted(["back2", "top10", "top2", "back1", "top1"], key=key) == ["top1", "top2", "top10", "back1", "back2"]
