"""Play one track: audio out, DMX out, and the visualiser feed. Clocked by the audio that is audible."""

from __future__ import annotations

import asyncio
import time

from amadeus.audio.model import Analysis
from amadeus.director import Decision
from amadeus.dmx.outputs import drives_real_lights, open_output
from amadeus.engine import Engine
from amadeus.engine.realism import Realism
from amadeus.show import feed as feedlib
from amadeus.show.arc import countdown_drop
from amadeus.show.clock import AudioClock, WallClock, light_lead
from amadeus.web.server import serve as serve_http


async def play(
    a: Analysis,
    plan: list[Decision],
    rig: dict,
    *,
    director: str,
    audio: bool = True,
    artnet_ip: str | None = None,
    start: float = 0.0,
    http_port: int = 8080,
    ws_port: int = 8765,
):
    """`artnet_ip`: None = visualiser only, "rig" = the set's output, an IP = that network node."""
    from websockets.asyncio.server import serve

    sender = open_output(rig, None if artnet_ip == "rig" else artnet_ip) if artnet_ip else None
    engine = Engine(a, plan, rig, real_output=drives_real_lights(sender, rig))
    universes = sorted({f["universe"] for f in rig["fixtures"]})
    period = 1.0 / rig["artnet"]["fps"]
    lead = light_lead(rig)
    real = Realism(rig)
    feed = feedlib.Feed(rig, real, period)
    title = feedlib.track_title(a.path)  # one track on its own: its main drop is the moment (no night to save it for)
    feed.set_hello(feedlib.hello(a, plan, rig, real, title=title, director=director, countdown=countdown_drop(a, plan)))
    bands = [a.band_norm(k) for k in a.bands_db]

    httpd = serve_http(http_port)
    print(f"Visualiser: http://localhost:{http_port}   (Ctrl+C to stop)")
    if sender:
        print(f"{sender.describe()}, universes {universes}")

    clock = AudioClock(a.path, start) if audio else WallClock(start)
    async with serve(feed.handler, "127.0.0.1", ws_port):
        clock.begin()
        last_phrase = -1
        next_tick = time.monotonic()
        try:
            while not clock.finished.is_set():
                next_tick += period  # absolute schedule: sleep jitter doesn't accumulate
                if time.monotonic() - next_tick > period:  # fell behind: skip the missed frames, no burst
                    next_tick = time.monotonic()
                t = clock.now() + lead  # the lights a little ahead, so they show on the beat
                if t >= a.duration:
                    break
                i, states = engine.render(t)
                if i != last_phrase:
                    d = plan[i]
                    print(
                        f"  {int(t // 60)}:{int(t % 60):02d}  {d.section:<9} {d.summary()} "
                        f"int={d.intensity} [{d.source}]"
                    )
                    last_phrase = i
                if sender:
                    sender.send(engine.dmx(states))
                if feed.watched:
                    beat, phase, _ = engine.beat_info(t)
                    guard = feedlib.guard_notes(engine)
                    status = {
                        "t": round(t, 3),
                        "phrase": i,
                        "beat": beat,
                        "bp": round(beat + phase, 3),
                        **({"guard": guard} if guard else {}),
                    }

                    def fixtures(t=t, states=states):
                        f = min(int(t * a.fps), len(bands[0]) - 1)
                        lasers = engine.laser_beams(states, t) if engine.lasers else None
                        return {"bands": [round(float(b[f]), 3) for b in bands], **feed.fixture_fields(states, lasers)}

                    feed.send(status, fixtures)
                await asyncio.sleep(max(0.0, next_tick - time.monotonic()))
        finally:
            clock.stop()
            if sender:
                sender.blackout(universes)
                sender.close()
            httpd.shutdown()
            print("Stopped" + (" (DMX blacked out)" if sender else ""))
