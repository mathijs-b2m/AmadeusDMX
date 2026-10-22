"""What a venue's documents say about its lights, before it is a set and a rig: one `Item` per fixture.

Every reader (MVR, a patch sheet) fills in what its document knows and leaves the rest empty; `resolve` finds
the fixture in the library, `layout` hangs it. Positions are in the importer's own frame: `s` metres to stage
right of the centre line, `y` metres towards the audience from the stage's front edge, `z` up from the stage
floor (the rig's x is `s` plus half the stage width, once the width is known).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    name: str  # the fixture type as the document calls it ("Mac Aura", "Martin@MAC Aura XB")
    label: str = ""  # its number or name in the document (#201, "101")
    mode: str = ""  # the DMX mode named there
    channels: int = 0  # its footprint, when the document says (a GDTF mode) or the patch spacing shows it
    universe: int = 0  # 0: not patched
    address: int = 0
    count: int = 1  # a sheet row for several of the same, addressed one after the other
    pos: tuple[float, float, float] | None = None  # (s, y, z) metres, see above
    beam: tuple[float, float, float] | None = None  # where it points (a unit vector, same frame)
    hanging: bool | None = None  # upside down under a truss (None: the document doesn't say)
    where: str = ""  # a position the document names ("Truss 1", "hall", "floor")
    source: str = ""  # which file (and row or node), for the report
    page: tuple[int, float, float] | None = None  # placed from a drawing: (its underlay, x, y on the page 0..1)


@dataclass
class Note:
    """One line of the import report: what was assumed, guessed or is missing, for the person to check."""

    level: str  # "ok", "check" (a guess worth a look), "missing" (left out, or must be filled in)
    text: str
    ids: list[str] = field(default_factory=list)  # the fixtures it is about


@dataclass
class Draft:
    items: list[Item] = field(default_factory=list)
    trusses: list[dict] = field(default_factory=list)  # named structure from the document: {name, s, y, z, dir}
    notes: list[Note] = field(default_factory=list)
    stage: dict = field(default_factory=dict)  # what the documents say: width_m, depth_m, ceiling_m (grid)
    underlays: list[dict] = field(default_factory=list)  # the plans fixtures were placed from (underlay.py)

    def note(self, level: str, text: str, ids: list[str] | None = None) -> None:
        self.notes.append(Note(level, text, ids or []))

    def merge(self, other: Draft) -> None:
        self.items += other.items
        self.trusses += other.trusses
        self.notes += other.notes
        self.stage.update({k: v for k, v in other.stage.items() if v})
        n = len(self.underlays)
        for it in other.items:
            if it.page:
                it.page = (it.page[0] + n, it.page[1], it.page[2])
        self.underlays += other.underlays
