import json

import pytest

from tests.golden_tool import GOLDEN, SETS, platform_tag, render_hash

RECORDED = json.loads(GOLDEN.read_text())

pytestmark = pytest.mark.skipif(
    RECORDED["_platform"] != platform_tag(),
    reason=f"golden hashes were recorded on {RECORDED['_platform']} (run tests/golden_tool.py --update there)",
)


@pytest.mark.parametrize("set_path", sorted(SETS.glob("*.json")), ids=lambda p: p.stem)
def test_dmx_output_unchanged(set_path):
    assert render_hash(set_path) == RECORDED[set_path.stem]
