"""Importing a venue's documents from the apps: the import as a job (reading PDFs with AI takes a minute), and
the drawings under the rig (rig/importer/underlay.py): list them, their pages, line one up again, remove one.

POST /api/import            {"name", "files": [{"name", "data": base64}], "replace": bool}: start; {"job"}
GET  /api/import?job=…      {"state": running|done|failed|cancelled, "step", "notes", "name", "fixtures", "trusses",
                            "error"}
POST /api/import/cancel     {"job"}: stop it at its next step (between two AI requests); nothing is saved
GET  /api/underlays?rig=…   the rig's drawings, each with its corners on the rig (metres) to draw it
GET  /api/underlay/page?file=…   one drawing's page (a one-page PDF)
POST /api/underlay/align    {"rig", "id", "a": [x, y], "b": [x, y], "width_m"}: line it up (page fractions of
                            the stage's front edge, stage left then stage right); its fixtures move with it
POST /api/underlay/remove   {"rig", "id"}: take the drawing away (the fixtures stay where they are)
"""

from __future__ import annotations

import base64
import shutil
import threading
import uuid
from pathlib import Path

from amadeus import paths
from amadeus.web.events import event

JOBS: dict[str, dict] = {}


def start_import(req):
    from amadeus.rig import store

    b = req.body()
    name = store.safe_name(b.get("name") or "")
    if not name:
        return {"error": "Give the set and rig a name"}, 400
    if not b.get("replace") and (name in store.sets.names() or name in store.rigs.names()):
        return {"error": f"A set or rig called “{name}” exists already"}, 409
    files = b.get("files") or []
    if not files:
        return {"error": "No files to import"}, 400
    job = uuid.uuid4().hex[:12]
    folder = paths.CACHE / "import-uploads" / job
    folder.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        p = folder / Path(f["name"]).name  # a name only: never a path out of the folder
        p.write_bytes(base64.b64decode(f["data"]))
        saved.append(p)
    JOBS[job] = {"state": "running", "step": "Reading the files…", "notes": [], "name": name}
    threading.Thread(target=_run, args=(job, saved, name, folder), daemon=True).start()
    event(f"{req.client} import: {name} from {', '.join(p.name for p in saved)}")
    return {"job": job}


class Cancelled(Exception):
    pass


def _run(job: str, files: list[Path], name: str, folder: Path):
    from amadeus.rig import importer, store

    state = JOBS[job]

    def progress(text: str):
        if state.get("cancel"):
            raise Cancelled
        state.update(step=text)

    try:
        result = importer.build(files, name, progress=progress)
        if state.get("cancel"):
            raise Cancelled
        state["notes"] = result.report()
        if not result.set_doc.get("fixtures"):
            state.update(state="failed", error="No fixtures found in these files")
            return
        importer.save(result, name)
        store.sets.switch(name)
        store.rigs.switch(name)
        state.update(state="done", step="Done", fixtures=len(result.set_doc["fixtures"]),
                     trusses=len(result.rig_doc.get("trusses", [])),
                     underlays=len(result.rig_doc.get("underlays", [])))  # fmt: skip
        event(f"import: built {name} ({state['fixtures']} fixtures)")
    except Cancelled:
        state.update(state="cancelled", step="Cancelled")
        event(f"import: {name} cancelled")
    except Exception as e:  # noqa: BLE001 - the app shows it
        state.update(state="failed", error=f"{e.__class__.__name__}: {e}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def import_status(req):
    job = JOBS.get(req.query.get("job", ""))
    if job is None:
        return {"error": "unknown import"}, 404
    return job


def cancel_import(req):
    job = JOBS.get(req.body().get("job", ""))
    if job is None:
        return {"error": "unknown import"}, 404
    if job["state"] == "running":
        job.update(cancel=True, step="Cancelling…")
    return job


def _with_corners(u: dict) -> dict:
    from amadeus.rig.importer import underlay

    return {**u, "corners": [[round(x, 3), round(y, 3)] for x, y in underlay.corners(u)]}


def list_underlays(req):
    from amadeus.rig import store

    rig = store.safe_name(req.query.get("rig") or req.show.rig)
    return {"underlays": [_with_corners(u) for u in store.rigs.load(rig).get("underlays", [])]}


def underlay_page(req):
    from amadeus.rig.importer import underlay

    return underlay.page_bytes(req.query.get("file", ""))


def align_underlay(req):
    from amadeus.rig import store
    from amadeus.rig.importer import underlay

    b = req.body()
    rig = store.safe_name(b["rig"])
    doc = store.rigs.load(rig)
    u = underlay.align(doc, b["id"], b["a"], b["b"], float(b["width_m"]))
    store.rigs.save(rig, doc)
    event(f"{req.client} underlay: {u['title']} lined up on {rig}")
    return {"underlay": _with_corners(u)}


def remove_underlay(req):
    from amadeus.rig import store

    b = req.body()
    rig = store.safe_name(b["rig"])
    doc = store.rigs.load(rig)
    doc["underlays"] = [u for u in doc.get("underlays", []) if u["id"] != b["id"]]
    if not doc["underlays"]:
        doc.pop("underlays")
    store.rigs.save(rig, doc)
    return {"underlays": [_with_corners(u) for u in doc.get("underlays", [])]}


GET = {"/api/import": import_status, "/api/underlays": list_underlays, "/api/underlay/page": underlay_page}
POST = {
    "/api/import": start_import,
    "/api/import/cancel": cancel_import,
    "/api/underlay/align": align_underlay,
    "/api/underlay/remove": remove_underlay,
}
