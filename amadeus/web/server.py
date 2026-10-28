"""HTTP server for the web UI: static files plus a small JSON API for the setup pages.

The handlers live by area: `rig` (the set, sets, outputs, patching), `library` (fixtures, search, label
photos) and `placement` (photo and 3D scan).

GET  /api/library            fixture definitions (model, kind, modes with channel counts)
GET  /api/rig                the rig file
POST /api/rig                validate and save the rig (returns problems; nothing saved if any)
POST /api/autopatch          assign non-overlapping addresses + stage layout to the posted fixtures
POST /api/discover           ArtPoll on the network; returns the nodes found
POST /api/identify           {"fixture": id, "rig": {...}}: light that fixture white for 2 s
POST /api/test-light         {"fixture": id, "rig": {...}, "on": bool}: keep that fixture lit (≤ 60 s) or stop;
                             "raw": [v, …] sends those values to its channels instead (the DMX mapper)
GET  /api/fixture/map?key=…&mode=…   a mode channel by channel, with the library's names and ranges (DMX mapper)
POST /api/fixture/map        {"key", "mode", "kind", "channels": [{"role", "cell", "value"}]}: save a hand mapping
                             ("wheel": colour wheel slots, "ring": a ring colour channel's, "checked": true from
                             the channel-by-channel check)
GET  /api/fixture/templates?type=spot&channels=9   common layouts to make a fixture without a brand from
POST /api/fixture/new        {"manufacturer", "model", "template", "channels", …}: make it in your library
POST /api/fixture/lens       {"key", "beam_deg", "beam_deg_max"?, "lumens"?}: its lens and light, as the manual says
POST /api/fixture/gdtf       {"name", "data": base64 .gdtf}: convert a GDTF file into your library (key, mode)
GET  /api/directors          decision models available right now (rules, OpenAI, local Ollama decision models)
POST /api/director           {"director": "..."}: switch the decision model (saved in the rig file on its own)
GET  /api/catalog?q=fuze     search our library + the QLC+, Open Fixture and DMXControl DDF libraries
GET  /api/catalog/details?key=...   modes and channels of one catalogue entry
POST /api/catalog/add        {"key": "qlc:..."}: convert it into fixtures/ and return its library key
POST /api/suggest            {"key", "mode", "count", "universe"}: free start addresses (packed / easy to dial)
POST /api/label              {"image": "data:image/jpeg;base64,..."}: recognise a fixture from its label photo
GET  /api/label/engines      image models available for that (OpenAI Decisions API, local Ollama vision)
POST /api/placement/lights   {"on": true, "batch": 0}: light every fixture in its own colour for the setup photo
POST /api/placement/analyze  {"image", "blobs", "batch"}: where each fixture is, mount, height, alignment → proposal
POST /api/placement/apply    {"changes": [...]}: write the accepted changes into the rig
POST /api/scan               raw PLY body (e.g. a Scaniverse export): find the lit fixtures in 3D → proposal
POST /api/scan/redo          {"scan", "flip", "moves"}: again with the audience on the other side / markers moved
GET  /api/sets               the sets (rigs side by side) and which one is active
POST /api/sets               {"active": "name"}: edit / default to that set · {"copy": "from", "name": "new"}
POST /api/rig/add            {"key", "mode", "addresses", "universe"}: add fixtures to the saved rig
GET  /api/outputs            DMX outputs: the set's, in words, and the USB DMX interfaces plugged in
GET  /api/devices            your DMX devices (config/devices.json) and the USB DMX interfaces plugged in
POST /api/devices            {"devices": [...]}: save them (a set maps its universes onto them: "dmx")
GET  /api/limiter            the brightness limiter: {"level": 0.05..1} (1: off)
POST /api/limiter            {"level": 0.7}: limit every light to that, in every running engine
POST /api/import             {"name", "files": [{"name", "data"}]}: build a set and rig from documents (a job)
GET  /api/import?job=…       how that import is going; its report when done
GET  /api/underlays?rig=…    the drawings under a rig; /api/underlay/page?file=… one's page (PDF)
POST /api/underlay/align     {"rig", "id", "a", "b", "width_m"}: line a drawing up (web/importer.py)
"""

from __future__ import annotations

import functools
import http.server
import json
import socket
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

from amadeus import paths
from amadeus.web import importer, library, placement, rig
from amadeus.web.events import event

GET = {**rig.GET, **library.GET, **placement.GET, **importer.GET}
POST = {**rig.POST, **library.POST, **placement.POST, **importer.POST}
QUIET = {"/api/log"}  # not logged as a request (they log themselves)


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files from web/, and the API routes. Route handlers get the handler as `req`: `req.query`,
    `req.body()`, `req.show` (the rig and set to work on), `req.fixed`, `req.client`, `req.headers`, `req.rfile`."""

    fixed = None  # a store.Selection: --rig/--set given (or a show is running); otherwise the active ones
    # the types the pages need, whatever the system says (Windows takes them from the registry, where .js is
    # often text/plain: then the browser refuses the visualiser's modules)
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".html": "text/html",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
        ".wasm": "application/wasm",
        ".png": "image/png",
    }

    @property
    def show(self):
        """The rig and set: `?rig=…&set=…` on the request, else the fixed ones, else the active ones."""
        from amadeus.rig import store

        q = getattr(self, "query", {}) or {}
        if q.get("rig") or q.get("set"):
            return store.current(q.get("rig"), q.get("set"))
        return self.fixed or store.current()

    @property
    def client(self) -> str:
        return self.client_address[0]

    def body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *args):
        pass

    def log_error(self, fmt, *args):
        event(f"{self.client} ERROR {fmt % args}")

    def handle_one_request(self):
        self._t0 = time.monotonic()
        super().handle_one_request()

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in GET:
            self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
            return self._route(GET[url.path], url.path)
        if url.path.endswith(".html"):
            event(f"{self.client} opened {url.path} ({self.headers.get('User-Agent', '')[:60]})")
        return super().do_GET()

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path not in POST:
            return self._reply({"error": "unknown endpoint"}, 404, url.path)
        self.query = {k: v[0] for k, v in parse_qs(url.query).items()}
        return self._route(POST[url.path], url.path)

    def _route(self, handler, path: str):
        try:
            result = handler(self)
        except SystemExit as e:  # e.g. port 6454 busy during discovery
            result = {"error": str(e)}, 409
        except Exception as e:  # noqa: BLE001 - report to the page instead of dropping the connection
            result = {"error": f"{e.__class__.__name__}: {e}"}, 400
        obj, status = result if isinstance(result, tuple) else (result, 200)
        self._reply(obj, status, path)

    def _reply(self, obj, status: int, path: str):
        if path not in QUIET:
            ms = (time.monotonic() - getattr(self, "_t0", time.monotonic())) * 1000
            event(f"{self.client} {self.command} {self.path[:80]} -> {status} ({ms:.0f} ms) {_summary(obj)}")
        page = isinstance(obj, str)  # a page (the hang sheet), not JSON
        pdf = isinstance(obj, bytes)  # a drawing's page (an underlay)
        data = obj if pdf else obj.encode() if page else json.dumps(obj).encode()
        self.send_response(status)
        kind = "application/pdf" if pdf else "text/html; charset=utf-8" if page else "application/json"
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _summary(obj) -> str:
    if isinstance(obj, dict):
        return obj.get("error") or ", ".join(list(obj)[:6])
    if isinstance(obj, list):
        return f"{len(obj)} items"
    if isinstance(obj, str):
        return f"{len(obj)} bytes of html"
    if isinstance(obj, bytes):
        return f"{len(obj)} bytes"
    return ""


class Server(http.server.ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"  # on Windows it would let a second server share the port


def serve(port: int, show=None, host: str = "127.0.0.1"):
    """Start the web UI server in a background thread; returns the server (call .shutdown()).

    host="0.0.0.0" makes it reachable from a phone on the same network (anyone on that network can
    then change the rig, so only on a network you trust)."""
    with socket.socket() as probe:  # macOS lets 0.0.0.0:port and 127.0.0.1:port coexist: refuse that mix-up
        probe.settimeout(0.3)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(
                f"Port {port} is already used by another process (a running `amadeus live`/`play`/"
                f"`setup`?). Stop it first, or use --port."
            )
    handler = functools.partial(type("H", (Handler,), {"fixed": show}), directory=str(paths.WEB))
    try:
        httpd = Server((host, port), handler)
    except OSError as e:
        raise SystemExit(
            f"Port {port} is in use: another show is probably still running (it would also send DMX "
            f"to the same lights). Stop it with Ctrl+C in its tab first, or use --port for a second "
            f"visualiser without --dmx."
        ) from e
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
