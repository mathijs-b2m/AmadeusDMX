# Import from documents: the apps (spec for Mac and Windows)

The engine side is done (`amadeus/rig/importer/`, `amadeus/web/importer.py`, docs/rig-format.md "Import from a
venue's documents"). Both apps get the same three pieces, built the same way.

## API (the setup service, as the other `/api/` calls)

| Request | Body / query | Answer |
|---|---|---|
| `POST /api/import` | `{"name", "files": [{"name", "data": <base64>}], "replace": bool}` | `{"job"}`; 409 `{"error"}` when the name is taken and not `replace` |
| `GET /api/import?job=…` | | `{"state": "running"\|"done"\|"failed", "step": text, "notes": [{"level": "ok"\|"check"\|"missing", "text", "ids": [fixture ids]}], "name", "fixtures", "trusses", "underlays", "error"}` |
| `GET /api/underlays?rig=…` | | `{"underlays": [U]}` |
| `GET /api/underlay/page?file=…` | | the page as a one-page PDF (`application/pdf`) |
| `POST /api/underlay/align` | `{"rig", "id", "a": [x, y], "b": [x, y], "width_m"}` | `{"underlay": U}`; the rig file is saved (fixtures and trusses moved) |
| `POST /api/underlay/remove` | `{"rig", "id"}` | `{"underlays": [U]}` |

`U` = `{"id", "title", "source", "file", "w", "h", "set", "a", "b", "a_m", "b_m", "fixtures": {id: [x, y]},
"corners": [[x_m, y_m] × 4]}`. `corners` are the page's top-left, top-right, bottom-right, bottom-left corners
on the rig, in rig metres: x from stage left (0) towards stage right, y from the stage's front edge towards the
audience (negative = upstage), the same frame as truss `x_m`/`y_m`. `a`/`b` and `fixtures` are page fractions
(0..1, from the page's top left). Importing PDFs takes up to a few minutes (AI): poll the job once a second.

## 1. Import from Documents… (Rigs page)

- Where: the Rigs page, a second full-width button under "New Rig…" in the rig list ("Import from Documents…",
  icon `doc.badge.arrow.up` / a document glyph), and the same item in the rig name menu (after Duplicate).
- A sheet: **Files** (an open panel, several at once: `.pdf .mvr .csv .tsv .txt .xlsx .xlsm`; the list shows
  them, each removable), **Name** for the set and rig (default: the first file's name, lower case, safe), a line
  saying what will be read: "MVR files and patch sheets are read here. PDFs (patch lists, riders, light plots)
  are read with AI using your own OpenAI API key; every page is sent to OpenAI." When a PDF is picked and there
  is no key in the app (Keychain / Credential Manager, the same key the AI director uses), say so and offer
  "Open Settings…" (to the OpenAI key); Import stays disabled for PDFs without a key.
- Import: post the files, then a progress view with the job's `step` and a spinner, and Cancel (closes the
  sheet; the job finishes on its own). A 409 asks "Replace the set and rig “name”?" and posts again with
  `replace: true`.
- Done: the report, grouped: the `missing` lines first (✗, red), then `check` (?, orange), then `ok` (✓, green);
  each line with its text; a line with `ids` can be clicked to select those fixtures in the editor once it is
  open. Buttons: "Open in Rig Editor" (default: switches the Rigs page to the new rig with the new set showing,
  `editingRig = name`, `editingRigSet = name`, reloads sets/rigs) and "Close". Failed: the error and the notes.

## 2. The drawing under the rig (rig editor)

- The editor loads `GET /api/underlays?rig=` with the rig, and each page (`/api/underlay/page`), rendered to an
  image once (Mac: PDFKit `PDFPage.thumbnail` / `CGPDFDocument`; Windows: `Windows.Data.Pdf.PdfDocument`), about
  2048 px on the long side.
- It is drawn on the stage floor (z a few mm above it) as a textured quad on its four `corners`, semi-transparent
  (default 50 %), under the trusses and fixtures, in every camera; best seen from Plan view. Only the drawings
  whose `set` is the set showing, or all when the rig is shown alone.
- A "Drawings" menu in the editor toolbar (only when the rig has some): per drawing a checkmark to show/hide it
  (remembered per rig in the app's settings), an opacity choice (25/50/75 %), "Line Up…" and "Remove…"
  (confirmation: "the fixtures stay where they are"). With one drawing those are direct items.

## 3. Line Up… (two clicks)

- A sheet with the page large (zoomable is a plus, fitting the sheet is enough), and an instruction: "Click the
  stage's front edge at stage left, then at stage right." Stage left is the performers' left; on the usual
  plan (audience at the bottom) that is on the right of the page. On a hall plan without the stage, click where
  the hall meets the stage, at its two side walls, and type the hall's width.
- The first click puts a marker "SL", the second "SR" (a line between them); clicking again starts over.
  A field **Distance** in metres between them, default the rig's stage width.
- The current reference (`a`, `b`) is shown as faint markers when the sheet opens, so you see what the import
  thought.
- "Line Up" posts `/api/underlay/align` (a = the SL click, b = the SR click, page fractions) and reloads the
  editor from the saved rig (if the editor has unsaved changes, ask first: "Save your changes first?" Save /
  Discard / Cancel). Its fixtures and their trusses move; a message "Lined up: N fixtures moved".

Everything as the rest of the app: the same sheet styles, glass toolbar buttons on the Mac, the same help texts on
both. Mac first is the spec, Windows the port; both in this round.
