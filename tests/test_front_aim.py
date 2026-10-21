"""The rig editor's light test points a moving head straight out to the audience, wherever and however it is
placed: turned in the app, the same beam needs another pan (the real head shows the difference)."""

import numpy as np

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry, hangsheet
from amadeus.rig.loader import load_rig_dict


def _fuze(**place):
    rig = load_rig_dict({"fixtures": [{"id": "h", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 1,
                                       "address": 1, "x": 0.5, "y_m": -1, **place}]})  # fmt: skip
    f = rig["fixtures"][0]
    return f, fxlib.get(f["fixture"])


def test_the_beam_points_at_the_audience_however_it_is_placed():
    for place in ({"z_m": 3.0, "mount": "hang"}, {"z_m": 0.25, "mount": "floor"}, {"z_m": 3.0, "mount": "hang", "rot_deg": 90}):
        f, d = _fuze(**place)
        beam = geometry.fk(f, d, *hangsheet.front_aim(f, d))
        assert np.allclose(beam, hangsheet.front_dir(f), atol=0.02)
        assert beam[1] > 0.9 and (beam[2] < 0) == (place["mount"] == "hang")  # out front; down when hanging


def test_turned_in_the_app_it_takes_another_pan():
    straight, turned = _fuze(z_m=3.0, mount="hang"), _fuze(z_m=3.0, mount="hang", rot_deg=90)
    assert hangsheet.front_aim(*straight)[0] != hangsheet.front_aim(*turned)[0]
