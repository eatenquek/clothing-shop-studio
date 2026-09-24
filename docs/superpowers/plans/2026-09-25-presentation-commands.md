# Presentation Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `extract`, `create_models`, `try_on`, and `create_listing` to the clothing-shop-studio skill so a seller can turn their own approved designs into catalogue cut-outs, AI-model try-ons, and a Taobao-style listing concept.

**Architecture:** Each command follows the existing plan → render → register pattern:
- **Plan:** the script returns image jobs.
- **Render:** the host agent's image tool renders them.
- **Register:** the script hashes and records the files with lineage.

State changes go through new hash-chained event types. They are applied by a small `presentation_state.py` that `store.py` calls, and they create new state keys lazily so legacy projects replay unchanged. Pages (`catalogue.html`, `listing-concept.html/.svg`) are static, escaped, stdlib-rendered files.

**Tech Stack:** Python 3.9+ standard library only (`zlib`, `struct`, `html`, `json`, `re`, `shutil`, `hashlib`), `unittest`, and the existing `studio_core` modules.

**Spec:** `docs/superpowers/specs/2026-09-25-presentation-commands-design.md`

## Global Constraints

- Python 3.9+ and stdlib only. Every new module starts with `from __future__ import annotations`.
- There are no network calls, API keys, or third-party packages. Images come from the host agent's image tool.
- There is no pricing, size chart, inventory, order, or storefront output anywhere.
- Every presentation file is `production_eligible: false`, and the master-lineage checks treat it as generated content.
- New state keys are created only when a presentation event is applied. `_state_template` must not change.
- Extraction outputs use a `#FFFFFF` background, are square, and are at least 1200 px.
- Poses are `front`, `three_quarter`, and `back`. Four default models ship in `assets/models/`.
- User decisions use `interview.decision_problem(...)`:
  - `CONFIRMATION_CUES` for the inventory confirmation and transmission consent;
  - `APPROVAL_CUES` for the model, try-on, and listing keep decisions.
- Every refusal is a `ValidationError` or `UnsafePathError`. Presentation refusals carry `details=[{"code": <code>, "message": <message>}]`, where the code is one of `inventory_unconfirmed`, `transmission_consent_missing`, `garment_not_listing_eligible`, `model_not_kept`, `real_person_model_refused`, or `decision_not_affirmative`.
- The listing concept contains no text except the design name, grey placeholder bars, and the tag `Concept — not a live listing`.
- The seller notice goes after every newly generated presentation output and before the single closing question. This is enforced by docs and evals.
- Run tests with `PYTHONDONTWRITEBYTECODE=1`, from `skill/clothing-shop-studio`:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
  ```

## Review Focus

1. **A legacy project gains no `presentation` key until a presentation command is used.** Otherwise `validate` reports `state_tampered`. The test goes in Task 1.
2. **User-controlled strings rendered into HTML/SVG must be escaped.** These are garment names, tags, `observed` notes, and design names. A name like `<script>` must appear as text. Hex colours must match `^#[0-9A-F]{6}$` before entering CSS. Tests go in Tasks 3 and 6.
3. **An image registered at a path other than its planned destination, or with a wrong signature, is refused.** Examples: a `.png` that is really text, or an empty file. The test goes in Task 1 (`check_image`).
4. **A garment extracted from a third-party or unconfirmed reference must not reach `try_on` or `create_listing`,** even when it has been kept. Tests go in Tasks 5 and 6.
5. **A model photo in the library that changes after a project used it must not silently alter that project.** The project pins the model's hash, and a mismatch is `file_hash_mismatch` in `validate`. The test goes in Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `scripts/studio_core/presentation_state.py` | Apply presentation events to state; lazy keys; no store import. |
| Create `scripts/studio_core/presentation.py` | Shared folders, `presentation_error`, `check_image`, lineage eligibility, decisions, library root. |
| Create `scripts/studio_core/pngcolour.py` | Stdlib PNG decode (8-bit, non-interlaced) and primary/secondary colour. |
| Create `scripts/studio_core/extract.py` | Inventory, confirmation, consent, extraction jobs, registration, `catalogue.html`. |
| Create `scripts/studio_core/models.py` | Identity cards, real-person backstop, defaults, candidate/reference jobs, keep, pin. |
| Create `scripts/studio_core/tryon.py` | Try-on jobs and registration. |
| Create `scripts/studio_core/listing.py` | Listing concept HTML/SVG build. |
| Modify `scripts/studio_core/store.py:224-266` | Dispatch presentation events. |
| Modify `scripts/studio_core/validation.py:31-37,121-132` | Presentation origin folders; generated-lineage origins. |
| Modify `scripts/studio_core/approval.py:55-64` | Schema-conformant `details` (`code` and `message`). |
| Modify `scripts/studio.py` | Four new commands. |
| Modify `schemas/command-io.schema.json` | New command names. |
| Create `assets/models/<id>/identity.json` ×4 | Default AI model identity cards. |
| Create `references/presentation.md` | Agent workflow for the four commands and their error codes. |
| Modify `SKILL.md`, `references/safety-scope.md`, `README.md` | Description, one rule, one router line, scope wording. |
| Create `evals/scenarios/presentation-*.json` and `near-miss-*.json` (both the `evals/` copies) | Trigger evals. |
| Tests: `tests/test_presentation.py`, `tests/test_pngcolour.py`, `tests/test_extract.py`, `tests/test_models.py`, `tests/test_tryon.py`, `tests/test_listing.py`, plus additions to `tests/test_cli.py`, `tests/test_structure.py`, `tests/test_approval.py` | |

All paths below are relative to `skill/clothing-shop-studio/` unless they start with `docs/`, `evals/`, or `README.md`.

---

### Task 1: Presentation core (state, folders, image checks, lineage, decisions)

**Files:**
- Create: `scripts/studio_core/presentation_state.py`, `scripts/studio_core/presentation.py`
- Modify: `scripts/studio_core/store.py`, `scripts/studio_core/validation.py`, `scripts/studio_core/approval.py`
- Modify: `tests/helpers.py` (add `make_png`)
- Test: `tests/test_presentation.py`, `tests/test_approval.py`

**Interfaces:**
- Produces:
  - `presentation_state.PRESENTATION_EVENTS: set[str]`
  - `presentation_state.apply_presentation_event(state: dict, event: dict) -> dict`
  - `presentation.PRESENTATION_FOLDERS: dict[str, str]`
  - `presentation.presentation_error(code: str, message: str, recovery: str, field: str | None = None, path: str | None = None) -> ValidationError`
  - `presentation.sha256(path: Path) -> str`
  - `presentation.check_image(project: Path, relative: str, folder: str, field: str = "path") -> tuple[Path, str]`
  - `presentation.file_index(state: dict) -> dict[str, dict]`
  - `presentation.listing_eligible(entry: dict, files: dict[str, dict]) -> bool`
  - `presentation.require_decision(quote, cues) -> str`
  - `presentation.record_decision(project: Path, kind: str, ids: list[str], decision: str, user_quote: str, now: str | None = None) -> dict`
  - `presentation.kept_ids(state: dict, kind: str) -> set[str]`
  - `presentation.register_entries(project: Path, entries: list[dict], now: str | None) -> None`
  - `presentation.library_root(project: Path) -> Path`
  - `presentation.next_round(state: dict, origin: str, group_key: str, group: str) -> int`
  - `tests.helpers.make_png(width, height, rows, colour_type=6, filter_type=0, palette=None) -> bytes`

- [ ] **Step 1: Add the PNG test helper and write the failing tests**

Append to `tests/helpers.py` (later tasks reuse it):

```python
def make_png(width: int, height: int, rows: list[list[tuple]], colour_type: int = 6, filter_type: int = 0,
             palette: list[tuple] | None = None) -> bytes:
    """Encode an 8-bit PNG with one filter type on every row (stdlib only)."""
    import struct
    import zlib

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour_type]

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    raw = bytearray()
    previous = bytes(width * channels)
    for row in rows:
        current = bytes(value for pixel in row for value in (pixel if isinstance(pixel, tuple) else (pixel,)))
        out = bytearray()
        for index, value in enumerate(current):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            corner = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                value = (value - left) % 256
            elif filter_type == 2:
                value = (value - up) % 256
            elif filter_type == 3:
                value = (value - (left + up) // 2) % 256
            elif filter_type == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                value = (value - predictor) % 256
            out.append(value)
        raw += bytes([filter_type]) + out
        previous = current
    body = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0))
    if colour_type == 3:
        body += chunk(b"PLTE", bytes(value for rgb in palette for value in rgb))
    body += chunk(b"IDAT", zlib.compress(bytes(raw)))
    return b"\x89PNG\r\n\x1a\n" + body + chunk(b"IEND", b"")
```

`tests/test_presentation.py`:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import UnsafePathError, ValidationError
from scripts.studio_core.presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    kept_ids,
    library_root,
    listing_eligible,
    record_decision,
    register_entries,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import master_problems, validate_project
from tests.helpers import FIXED_NOW, make_png, make_project, ready_project

PNG_1PX = make_png(1, 1, [[(0, 0, 0, 255)]])


def write(project: Path, relative: str, data: bytes) -> str:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return relative


class PresentationCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = make_project(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_project_state_gains_no_presentation_key(self):
        project = ready_project(self.root, name="Legacy shape")
        self.assertNotIn("presentation", load_state(project))
        self.assertEqual(validate_project(project)["errors"], [])

    def test_check_image_refuses_wrong_folder_signature_and_empty(self):
        folder = PRESENTATION_FOLDERS["extracted_garment"]
        good = write(self.project, f"{folder}src/r01/tee.png", PNG_1PX)
        self.assertEqual(check_image(self.project, good, folder)[1], good)
        with self.assertRaises(UnsafePathError):
            check_image(self.project, write(self.project, "concepts/generated/x.png", PNG_1PX), folder)
        for name, data in (("fake.png", b"not a png"), ("empty.png", b""), ("doc.txt", b"text")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                check_image(self.project, write(self.project, f"{folder}src/r01/{name}", data), folder)

    def test_presentation_files_are_generated_for_master_checks(self):
        relative = write(self.project, "presentation/extracted/src/r01/tee.png", PNG_1PX)
        entry = {"id": "xg-001", "origin": "extracted_garment", "path": relative, "sha256": "0" * 64,
                 "parents": [], "registered_at": FIXED_NOW, "production_eligible": False}
        register_entries(self.project, [entry], FIXED_NOW)
        master = {"id": "master-x", "origin": "production_master", "path": "production/masters/x_MASTER.png",
                  "parents": ["xg-001"], "construction": "user_supplied"}
        codes = [item["code"] for item in master_problems(master, {"xg-001": entry})]
        self.assertTrue({"master_generated_raster", "master_generated_concept"} & set(codes), codes)

    def test_listing_eligibility_follows_rights_lineage(self):
        files = {
            "ref-own": {"id": "ref-own", "origin": "user_reference", "rights": "user-owned-or-licensed", "parents": []},
            "ref-3p": {"id": "ref-3p", "origin": "user_reference", "rights": "third-party-inspiration-only", "parents": []},
            "ref-web": {"id": "ref-web", "origin": "online_reference", "parents": []},
            "v001-a": {"id": "v001-a", "origin": "approved_design", "parents": ["c-a"]},
            "c-a": {"id": "c-a", "origin": "generated_concept", "parents": []},
            "m-1": {"id": "m-1", "origin": "synthetic_model", "parents": []},
        }
        own = {"id": "x1", "origin": "extracted_garment", "parents": ["ref-own"]}
        third = {"id": "x2", "origin": "extracted_garment", "parents": ["ref-3p"]}
        web = {"id": "x3", "origin": "extracted_garment", "parents": ["ref-web"]}
        design = {"id": "t1", "origin": "tryon_image", "parents": ["v001-a", "m-1"]}
        self.assertTrue(listing_eligible(own, files))
        self.assertFalse(listing_eligible(third, files))
        self.assertFalse(listing_eligible(web, files))
        self.assertTrue(listing_eligible(design, files))

    def test_decisions_need_affirmative_keep_and_latest_wins(self):
        with self.assertRaises(ValidationError) as caught:
            record_decision(self.project, "tryon", ["t1"], "keep", "Yes, but make it brighter", FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "decision_not_affirmative")
        record_decision(self.project, "tryon", ["t1"], "keep", "Keep it, yes", FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), {"t1"})
        record_decision(self.project, "tryon", ["t1"], "drop", "Drop that one", FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), set())
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_library_root_is_beside_projects(self):
        self.assertEqual(library_root(self.project), self.project.parent / "_models")


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_approval.py`, inside `ApprovalTests`:

```python
    def test_refusal_details_follow_the_error_schema(self):
        with self.assertRaises(ValidationError) as caught:
            approve_design(self.project, [self.concepts["A"]["id"]], "Yes, but change the sleeve", now=FIXED_NOW)
        detail = caught.exception.details[0]
        self.assertEqual(detail["code"], "revision")
        self.assertIn("message", detail)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_presentation tests.test_approval
```

Expected: `ModuleNotFoundError: scripts.studio_core.presentation`, and a `KeyError: 'code'` in the approval test.

- [ ] **Step 3: Implement**

`scripts/studio_core/presentation_state.py`:

```python
"""Apply presentation events to project state.

Kept free of store imports so store.py can call it. Every key is created on first
use, so a project that never runs a presentation command replays to exactly the
state it had before these commands existed.
"""

from __future__ import annotations

PRESENTATION_EVENTS = {
    "inventory_recorded",
    "inventory_confirmed",
    "transmission_consent",
    "presentation_decision",
    "listing_built",
}


def apply_presentation_event(state: dict, event: dict) -> dict:
    kind = event["type"]
    if kind == "inventory_recorded":
        state.setdefault("presentation", {}).setdefault("inventories", []).append(dict(event["inventory"]))
    elif kind == "inventory_confirmed":
        for inventory in state.get("presentation", {}).get("inventories", []):
            if inventory["id"] == event["inventory_id"]:
                inventory["confirmed"] = True
                inventory["user_quote"] = event["user_quote"]
    elif kind == "transmission_consent":
        for entry in state.get("files", []):
            if entry["id"] == event["file_id"]:
                entry["external_transmission_consent"] = True
                entry["consent_quote"] = event["user_quote"]
    elif kind == "presentation_decision":
        state.setdefault("presentation", {}).setdefault("decisions", []).append(
            {key: event[key] for key in ("kind", "ids", "decision", "user_quote", "timestamp")}
        )
    elif kind == "listing_built":
        state.setdefault("presentation", {}).setdefault("listings", []).append(dict(event["listing"]))
    return state
```

In `scripts/studio_core/store.py`, add the import after the existing interview import:

```python
from .presentation_state import PRESENTATION_EVENTS, apply_presentation_event
```

In `_apply_event`, before `next_state["updated_at"] = ...`, add:

```python
    elif event_type in PRESENTATION_EVENTS:
        next_state = apply_presentation_event(next_state, event)
```

`scripts/studio_core/presentation.py`:

```python
"""Shared rules for presentation images: folders, file checks, lineage, decisions."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import resolve_inside
from .errors import ValidationError
from .interview import APPROVAL_CUES, decision_problem
from .store import append_event, load_state

PRESENTATION_FOLDERS = {
    "extracted_garment": "presentation/extracted/",
    "synthetic_model": "presentation/models/",
    "tryon_image": "presentation/tryon/",
    "listing_concept": "presentation/listing/",
}
IMAGE_SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}
DECISIONS = ("keep", "regenerate", "drop")
MODELS_DIRNAME = "_models"


def presentation_error(code: str, message: str, recovery: str, field: str | None = None,
                       path: str | None = None) -> ValidationError:
    return ValidationError(message, field=field, path=path, recovery=recovery,
                           details=[{"code": code, "message": message}])


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_image(project: Path, relative: str, folder: str, field: str = "path") -> tuple[Path, str]:
    """Require a non-empty PNG or JPEG inside `folder` whose bytes match its extension."""
    absolute, normalised = resolve_inside(project, relative, folder, field)
    signature = IMAGE_SIGNATURES.get(absolute.suffix.lower())
    if signature is None:
        raise ValidationError("Presentation images must be PNG or JPEG.", field=field, path=normalised,
                              recovery="Save the rendered image as .png or .jpg and register it again.")
    data = absolute.read_bytes()
    if not data or not data.startswith(signature):
        raise ValidationError("The image is empty or its content does not match its extension.",
                              field=field, path=normalised,
                              recovery="Save the actual rendered image at the planned destination.")
    return absolute, normalised


def file_index(state: dict) -> dict[str, dict]:
    return {item["id"]: item for item in state.get("files", [])}


def listing_eligible(entry: dict, files: dict[str, dict]) -> bool:
    """True when no ancestor is third-party, unconfirmed, or an online reference."""
    stack, seen = list(entry.get("parents") or []), set()
    while stack:
        parent_id = stack.pop()
        if parent_id in seen:
            continue
        seen.add(parent_id)
        parent = files.get(parent_id)
        if parent is None:
            return False
        if parent.get("origin") == "online_reference":
            return False
        if parent.get("origin") == "user_reference" and parent.get("rights") != "user-owned-or-licensed":
            return False
        stack.extend(parent.get("parents") or [])
    return True


def require_decision(quote, cues=APPROVAL_CUES) -> str:
    problem = decision_problem(quote, cues)
    if problem:
        raise presentation_error(
            "decision_not_affirmative",
            f"The reply is not an unqualified yes ({problem}).",
            "Resolve the request, show the result again, and record the user's clear reply.",
            field="user_quote",
        )
    return quote.strip()


def record_decision(project: Path, kind: str, ids: list[str], decision: str, user_quote: str,
                    now: str | None = None) -> dict:
    if decision not in DECISIONS:
        raise ValidationError(f"Decision must be one of: {', '.join(DECISIONS)}.", field="decision",
                              recovery="Send keep, regenerate, or drop.")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) for item in ids):
        raise ValidationError("List the ids this decision covers.", field="ids",
                              recovery="Send the registered ids the user decided on.")
    quote = require_decision(user_quote) if decision == "keep" else str(user_quote or "").strip()
    if not quote:
        raise ValidationError("Record the user's words for this decision.", field="user_quote",
                              recovery="Pass the user's reply as `user_quote`.")
    state = append_event(project, {"type": "presentation_decision", "kind": kind, "ids": ids,
                                   "decision": decision, "user_quote": quote}, now)
    return state["presentation"]["decisions"][-1]


def kept_ids(state: dict, kind: str) -> set[str]:
    latest: dict[str, str] = {}
    for decision in state.get("presentation", {}).get("decisions", []):
        if decision["kind"] == kind:
            for item in decision["ids"]:
                latest[item] = decision["decision"]
    return {item for item, value in latest.items() if value == "keep"}


def register_entries(project: Path, entries: list[dict], now: str | None) -> None:
    append_event(project, {"type": "files_registered", "entries": entries}, now)


def library_root(project: Path) -> Path:
    return Path(project).parent / MODELS_DIRNAME


def next_round(state: dict, origin: str, group_key: str, group: str) -> int:
    rounds = {item.get("round") for item in state.get("files", [])
              if item.get("origin") == origin and item.get(group_key) == group}
    return 1 + max((value for value in rounds if isinstance(value, int)), default=0)
```

In `scripts/studio_core/validation.py`:

- Add the import:

  ```python
  from .presentation import PRESENTATION_FOLDERS
  ```

- Extend the folder map after `ORIGIN_FOLDERS` is defined:

  ```python
  ORIGIN_FOLDERS.update(PRESENTATION_FOLDERS)
  GENERATED_ORIGINS = {"generated_concept", *PRESENTATION_FOLDERS}
  ```

- In `_generated_ancestors`, replace `if current.get("origin") == "generated_concept":` with:

  ```python
          if current.get("origin") in GENERATED_ORIGINS:
  ```

`presentation.py` imports `store`, and `validation.py` imports `presentation`. Neither imports `validation`, so there is no import cycle.

In `scripts/studio_core/approval.py`, replace `details=[{"reason": problem}],` with:

```python
            details=[{"code": problem, "message": f"The statement contains a {problem} and cannot approve."}],
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK`, 134 existing tests plus the new ones.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio_core/presentation_state.py scripts/studio_core/presentation.py scripts/studio_core/store.py scripts/studio_core/validation.py scripts/studio_core/approval.py tests/helpers.py tests/test_presentation.py tests/test_approval.py
git commit -m "feat: add presentation core state, image checks, and lineage rules"
```

---

### Task 2: Stdlib PNG colour reader

**Files:**
- Create: `scripts/studio_core/pngcolour.py`
- Test: `tests/test_pngcolour.py`

**Interfaces:**
- Produces:
  - `pngcolour.decode_png(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]] | None`, returning RGBA pixels, or `None` when the format is unsupported;
  - `pngcolour.garment_colours(data: bytes) -> dict | None`, returning `{"primary": "#RRGGBB", "secondary": "#RRGGBB" | None}`;

- [ ] **Step 1: Write the failing tests**

`make_png` already exists in `tests/helpers.py` (added in Task 1).


`tests/test_pngcolour.py`:

```python
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.pngcolour import decode_png, garment_colours
from tests.helpers import make_png

WHITE, NAVY, RED = (255, 255, 255, 255), (20, 30, 90, 255), (200, 20, 30, 255)


def garment(width=20, height=20, stripe=None):
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            inside = 4 <= x < 16 and 4 <= y < 16
            colour = (stripe if stripe and inside and x < 8 else NAVY) if inside else WHITE
            row.append(colour)
        rows.append(row)
    return rows


class PngColourTests(unittest.TestCase):
    def test_every_filter_type_round_trips(self):
        rows = garment(stripe=RED)
        for filter_type in range(5):
            with self.subTest(filter_type=filter_type):
                width, height, pixels = decode_png(make_png(20, 20, rows, 6, filter_type))
                self.assertEqual((width, height), (20, 20))
                self.assertEqual(pixels[5 * 20 + 5], RED)
                self.assertEqual(pixels[0], WHITE)

    def test_greyscale_rgb_and_palette(self):
        grey = decode_png(make_png(2, 1, [[(0,), (255,)]], colour_type=0))
        self.assertEqual(grey[2], [(0, 0, 0, 255), (255, 255, 255, 255)])
        rgb = decode_png(make_png(1, 1, [[(1, 2, 3)]], colour_type=2))
        self.assertEqual(rgb[2], [(1, 2, 3, 255)])
        pal = decode_png(make_png(1, 1, [[(1,)]], colour_type=3, palette=[(0, 0, 0), (9, 8, 7)]))
        self.assertEqual(pal[2], [(9, 8, 7, 255)])

    def test_primary_ignores_white_background(self):
        self.assertEqual(garment_colours(make_png(20, 20, garment()))["primary"], "#141E5A")
        self.assertIsNone(garment_colours(make_png(20, 20, garment()))["secondary"])

    def test_secondary_needs_real_coverage(self):
        colours = garment_colours(make_png(20, 20, garment(stripe=RED)))
        self.assertEqual(colours["secondary"], "#C8141E")

    def test_unsupported_or_blank_images_return_none(self):
        self.assertIsNone(decode_png(b"not a png"))
        self.assertIsNone(garment_colours(make_png(2, 2, [[WHITE, WHITE], [WHITE, WHITE]])))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_pngcolour
```

Expected: `ModuleNotFoundError: scripts.studio_core.pngcolour`.

- [ ] **Step 3: Implement `scripts/studio_core/pngcolour.py`**

```python
"""Read garment colours from PNG files with the standard library only.

Supports 8-bit, non-interlaced greyscale, RGB, palette, grey+alpha, and RGBA PNGs.
Anything else returns None so the caller records an estimated colour instead.
"""

from __future__ import annotations

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_PIXELS = 40_000_000
BACKGROUND_MIN = 240
SECONDARY_SHARE = 0.15
DISTINCT_DISTANCE = 60


def _paeth(left: int, up: int, corner: int) -> int:
    p = left + up - corner
    pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
    return left if pa <= pb and pa <= pc else up if pb <= pc else corner


def decode_png(data: bytes):
    if not data.startswith(SIGNATURE):
        return None
    offset, header, palette, idat = 8, None, None, bytearray()
    try:
        while offset < len(data):
            length, kind = struct.unpack(">I4s", data[offset:offset + 8])
            body = data[offset + 8:offset + 8 + length]
            offset += 12 + length
            if kind == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif kind == b"PLTE":
                palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
            elif kind == b"IDAT":
                idat += body
            elif kind == b"IEND":
                break
        if header is None:
            return None
        width, height, depth, colour_type, _, _, interlace = header
        if depth != 8 or interlace != 0 or colour_type not in CHANNELS or width * height > MAX_PIXELS:
            return None
        if colour_type == 3 and not palette:
            return None
        raw = zlib.decompress(bytes(idat))
    except (struct.error, zlib.error):
        return None
    channels = CHANNELS[colour_type]
    stride = width * channels
    if len(raw) < height * (stride + 1):
        return None
    pixels, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        filter_type, line = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up, corner = previous[i], previous[i - channels] if i >= channels else 0
            if filter_type == 1:
                line[i] = (line[i] + left) % 256
            elif filter_type == 2:
                line[i] = (line[i] + up) % 256
            elif filter_type == 3:
                line[i] = (line[i] + (left + up) // 2) % 256
            elif filter_type == 4:
                line[i] = (line[i] + _paeth(left, up, corner)) % 256
            elif filter_type != 0:
                return None
        for x in range(width):
            values = line[x * channels:(x + 1) * channels]
            if colour_type == 0:
                pixels.append((values[0], values[0], values[0], 255))
            elif colour_type == 2:
                pixels.append((values[0], values[1], values[2], 255))
            elif colour_type == 3:
                if values[0] >= len(palette):
                    return None
                pixels.append((*palette[values[0]], 255))
            elif colour_type == 4:
                pixels.append((values[0], values[0], values[0], values[1]))
            else:
                pixels.append(tuple(values))
        previous = line
    return width, height, pixels


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(value):02X}" for value in rgb)


def garment_colours(data: bytes):
    decoded = decode_png(data)
    if decoded is None:
        return None
    _, _, pixels = decoded
    buckets: dict[tuple, list] = {}
    total = 0
    for r, g, b, a in pixels:
        if a < 128 or (r >= BACKGROUND_MIN and g >= BACKGROUND_MIN and b >= BACKGROUND_MIN):
            continue
        total += 1
        key = (r >> 4, g >> 4, b >> 4)
        bucket = buckets.setdefault(key, [0, 0, 0, 0])
        bucket[0] += 1
        bucket[1] += r
        bucket[2] += g
        bucket[3] += b
    if not total:
        return None
    ranked = sorted(buckets.values(), key=lambda item: item[0], reverse=True)
    means = [(count, (sr / count, sg / count, sb / count)) for count, sr, sg, sb in ranked]
    primary = means[0][1]
    secondary = None
    for count, colour in means[1:]:
        if count / total < SECONDARY_SHARE:
            break
        if sum((a - b) ** 2 for a, b in zip(colour, primary)) ** 0.5 >= DISTINCT_DISTANCE:
            secondary = colour
            break
    return {"primary": _hex(primary), "secondary": _hex(secondary) if secondary else None}
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_pngcolour
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio_core/pngcolour.py tests/test_pngcolour.py
git commit -m "feat: read garment colours from PNGs with the standard library"
```

---

### Task 3: `extract` (inventory, confirmation, consent, jobs, registration, catalogue)

**Files:**
- Create: `scripts/studio_core/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes (Task 1): `presentation_error`, `check_image`, `file_index`, `listing_eligible`, `register_entries`, `next_round`, `sha256`, `PRESENTATION_FOLDERS`.
- Consumes (Task 2): `garment_colours`.
- Consumes (Task 1): `tests.helpers.make_png`.
- Consumes: `interview.decision_problem` and `CONFIRMATION_CUES`; `store.append_event`, `load_state`, `write_atomic`.
- Produces:
  - `CATEGORIES = ("tops", "jackets", "bottoms", "accessories", "shoes")`
  - `GRAPHIC_POLICIES = ("exact", "mark-only", "omit")`
  - `record_inventory(project: Path, payload: dict, now: str | None = None) -> dict`, returning the inventory with `id` `inv-NNN`
  - `confirm_inventory(project: Path, payload: dict, now: str | None = None) -> dict`
  - `record_consent(project: Path, payload: dict, now: str | None = None) -> dict`, returning the updated file entry
  - `plan_extraction(project: Path, payload: dict) -> dict`, returning `{"inventory_id", "round", "jobs": [...]}`
  - `register_extraction(project: Path, payload: dict, now: str | None = None) -> dict`, returning `{"entries": [...], "catalogue": str}`
  - `render_catalogue(project: Path) -> Path`

- [ ] **Step 1: Write the failing tests**

`tests/test_extract.py`:

```python
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.extract import (
    confirm_inventory,
    plan_extraction,
    record_consent,
    record_inventory,
    register_extraction,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import register_file, validate_project
from tests.helpers import FIXED_NOW, make_png, make_project

NAVY, WHITE = (20, 30, 90, 255), (255, 255, 255, 255)
GARMENT = make_png(4, 4, [[WHITE, NAVY, NAVY, WHITE]] * 4)
ITEM = {"slug": "navy-tee", "name": "Navy tee", "category": "tops", "details": ["casual"],
        "observed": ["crew neck"], "bbox": [0.1, 0.1, 0.8, 0.9], "graphic_policy": "omit", "unknowns": []}


def code(error: ValidationError) -> str:
    return error.details[0]["code"] if error.details else ""


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self.temp.name))
        photo = self.project / "references/user/sample.png"
        photo.write_bytes(GARMENT)
        self.ref = register_file(self.project, {"origin": "user_reference", "path": "references/user/sample.png",
                                                "rights": "user-owned-or-licensed",
                                                "rights_statement": "My own sample."}, FIXED_NOW)

    def tearDown(self):
        self.temp.cleanup()

    def inventory(self, items=None):
        return record_inventory(self.project, {"source_id": self.ref["id"], "items": items or [ITEM]}, FIXED_NOW)

    def ready(self):
        inventory = self.inventory()
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes, that's right"}, FIXED_NOW)
        record_consent(self.project, {"file_id": self.ref["id"], "user_quote": "Yes"}, FIXED_NOW)
        return inventory

    def test_inventory_validates_items(self):
        for bad in ({**ITEM, "category": "hats"}, {**ITEM, "graphic_policy": "trace"},
                    {**ITEM, "bbox": [0.5, 0.5, 0.2, 0.9]}, {**ITEM, "slug": "Bad Slug"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.inventory([bad])
        with self.assertRaises(ValidationError):
            self.inventory([ITEM, ITEM])

    def test_plan_requires_confirmation_and_consent(self):
        inventory = self.inventory()
        with self.assertRaises(ValidationError) as caught:
            plan_extraction(self.project, {"inventory_id": inventory["id"]})
        self.assertEqual(code(caught.exception), "inventory_unconfirmed")
        with self.assertRaises(ValidationError):
            confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes, but add the cap"})
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Correct"}, FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_extraction(self.project, {"inventory_id": inventory["id"]})
        self.assertEqual(code(caught.exception), "transmission_consent_missing")

    def test_plan_jobs_follow_the_extraction_contract(self):
        inventory = self.ready()
        plan = plan_extraction(self.project, {"inventory_id": inventory["id"]})
        job = plan["jobs"][0]
        self.assertEqual(job["destination"], f"presentation/extracted/{self.ref['id']}/r01/navy-tee.png")
        self.assertEqual((job["background"], job["min_size"]), ("#FFFFFF", 1200))
        for phrase in ("Reconstruct ONLY the complete empty", "Prefer omission over invention", "Omit any"):
            self.assertIn(phrase, job["prompt"])

    def test_register_records_lineage_colour_and_catalogue(self):
        inventory = self.ready()
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(GARMENT)
        result = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                                    "results": [{"slug": "navy-tee", "path": destination,
                                                                 "renderer": "host-image-tool", "prompt": "p"}]},
                                     FIXED_NOW)
        entry = result["entries"][0]
        self.assertEqual((entry["origin"], entry["parents"], entry["primary_colour"]),
                         ("extracted_garment", [self.ref["id"]], "#141E5A"))
        self.assertTrue(entry["listing_eligible"])
        page = (self.project / result["catalogue"]).read_text("utf-8")
        self.assertIn("Navy tee", page)
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_register_refuses_unplanned_paths(self):
        inventory = self.ready()
        plan_extraction(self.project, {"inventory_id": inventory["id"]})
        stray = self.project / "presentation/extracted/elsewhere.png"
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(GARMENT)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1,
                                               "results": [{"slug": "navy-tee", "path": "presentation/extracted/elsewhere.png",
                                                            "renderer": "r", "prompt": "p"}]}, FIXED_NOW)

    def test_catalogue_escapes_names_and_rejects_bad_colours(self):
        inventory = self.inventory([{**ITEM, "name": "<script>alert(1)</script>", "details": ["<b>x</b>"]}])
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes"}, FIXED_NOW)
        record_consent(self.project, {"file_id": self.ref["id"], "user_quote": "Yes"}, FIXED_NOW)
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(b"\xff\xd8\xff" + b"jpeg-bytes")
        jpg = destination[:-4] + ".jpg"
        (self.project / destination).rename(self.project / jpg)
        with self.assertRaises(ValidationError):
            register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
                {"slug": "navy-tee", "path": jpg, "renderer": "r", "prompt": "p",
                 "estimated_colours": {"primary": "red;}</style><script>"}}]}, FIXED_NOW)
        result = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
            {"slug": "navy-tee", "path": jpg, "renderer": "r", "prompt": "p",
             "estimated_colours": {"primary": "#AA0000"}}]}, FIXED_NOW)
        page = (self.project / result["catalogue"]).read_text("utf-8")
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual(result["entries"][0]["colour_source"], "estimated")

    def test_third_party_source_is_inspiration_only(self):
        photo = self.project / "references/user/shop.png"
        photo.write_bytes(GARMENT)
        shop = register_file(self.project, {"origin": "user_reference", "path": "references/user/shop.png",
                                            "rights": "third-party-inspiration-only"}, FIXED_NOW)
        inventory = record_inventory(self.project, {"source_id": shop["id"], "items": [ITEM]}, FIXED_NOW)
        confirm_inventory(self.project, {"inventory_id": inventory["id"], "user_quote": "Yes"}, FIXED_NOW)
        record_consent(self.project, {"file_id": shop["id"], "user_quote": "Yes"}, FIXED_NOW)
        destination = plan_extraction(self.project, {"inventory_id": inventory["id"]})["jobs"][0]["destination"]
        (self.project / destination).parent.mkdir(parents=True, exist_ok=True)
        (self.project / destination).write_bytes(GARMENT)
        entry = register_extraction(self.project, {"inventory_id": inventory["id"], "round": 1, "results": [
            {"slug": "navy-tee", "path": destination, "renderer": "r", "prompt": "p"}]}, FIXED_NOW)["entries"][0]
        self.assertFalse(entry["listing_eligible"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_extract
```

Expected: `ModuleNotFoundError: scripts.studio_core.extract`.

- [ ] **Step 3: Implement `scripts/studio_core/extract.py`**

```python
"""Extract garments from a reference image into white-background catalogue cut-outs.

Workflow borrowed from the open Extract Clothing skill: inventory first, one job per
garment, prefer omission over invention, and an explicit text/logo policy.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from .errors import ValidationError
from .interview import CONFIRMATION_CUES, decision_problem
from .pngcolour import garment_colours
from .presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    file_index,
    listing_eligible,
    next_round,
    presentation_error,
    register_entries,
    sha256,
)
from .store import _utc_now, append_event, load_state, write_atomic

CATEGORIES = ("tops", "jackets", "bottoms", "accessories", "shoes")
GRAPHIC_POLICIES = ("exact", "mark-only", "omit")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
SOURCE_ORIGINS = {"user_reference", "approved_design"}
FOLDER = PRESENTATION_FOLDERS["extracted_garment"]
POLICY_TEXT = {
    "exact": "Reproduce the visible wording exactly as in the source crop; do not restyle it.",
    "mark-only": "Show the emblem's shape and placement only; do not invent readable text.",
    "omit": "Omit any printed text, logo, or emblem that the source does not clearly show.",
}


def _text_list(value, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValidationError(f"`{field}` must be a list of short text items.", field=field,
                              recovery=f"Send `{field}` as a JSON list of strings.")
    return [item.strip() for item in value]


def _item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValidationError("Each inventory item must be an object.", field="items",
                              recovery="Send one object per visible garment.")
    slug, name = raw.get("slug"), raw.get("name")
    if not isinstance(slug, str) or not SLUG.match(slug):
        raise ValidationError("Item slug must be lowercase letters, digits, and hyphens.", field="slug",
                              recovery="Use a slug such as `navy-crew-tee`.")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("Each item needs a name.", field="name", recovery="Name the garment as seen.")
    if raw.get("category") not in CATEGORIES:
        raise ValidationError(f"Category must be one of: {', '.join(CATEGORIES)}.", field="category",
                              recovery="Pick the closest catalogue category.")
    if raw.get("graphic_policy") not in GRAPHIC_POLICIES:
        raise ValidationError(f"Graphic policy must be one of: {', '.join(GRAPHIC_POLICIES)}.",
                              field="graphic_policy", recovery="Use `omit` when text or logos are unclear.")
    bbox = raw.get("bbox")
    if (not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in bbox)
            or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]):
        raise ValidationError("`bbox` must be [left, top, right, bottom] fractions with left<right, top<bottom.",
                              field="bbox", recovery="Send the garment's box as fractions of the image.")
    return {"slug": slug, "name": name.strip(), "category": raw["category"],
            "details": _text_list(raw.get("details"), "details"),
            "observed": _text_list(raw.get("observed"), "observed"),
            "bbox": [float(v) for v in bbox], "graphic_policy": raw["graphic_policy"],
            "unknowns": _text_list(raw.get("unknowns"), "unknowns"), "untrusted_text": True}


def _inventory(state: dict, inventory_id) -> dict:
    for inventory in state.get("presentation", {}).get("inventories", []):
        if inventory["id"] == inventory_id:
            return inventory
    raise ValidationError("Unknown inventory.", field="inventory_id", recovery="Run `extract` mode `inventory` first.")


def record_inventory(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    files = file_index(state)
    source = files.get(payload.get("source_id"))
    if source is None or source.get("origin") not in SOURCE_ORIGINS:
        raise ValidationError("Extract from a registered user reference or approved design.", field="source_id",
                              recovery="Register the photo with `register_file` (origin user_reference) first.")
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("List at least one visible garment.", field="items",
                              recovery="Send one item per garment you can see.")
    cleaned = [_item(item) for item in items]
    if len({item["slug"] for item in cleaned}) != len(cleaned):
        raise ValidationError("Item slugs must be unique.", field="slug", recovery="Give each garment its own slug.")
    count = len(state.get("presentation", {}).get("inventories", []))
    inventory = {"id": f"inv-{count + 1:03d}", "source_id": source["id"], "items": cleaned,
                 "target": payload.get("target"), "confirmed": False}
    append_event(project, {"type": "inventory_recorded", "inventory": inventory}, now)
    return inventory


def confirm_inventory(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    problem = decision_problem(payload.get("user_quote"), CONFIRMATION_CUES)
    if problem:
        raise presentation_error("inventory_unconfirmed", f"The garment list was not confirmed ({problem}).",
                                 "Apply the user's corrections with a new inventory, show it, and ask again.",
                                 field="user_quote")
    append_event(project, {"type": "inventory_confirmed", "inventory_id": inventory["id"],
                           "user_quote": payload["user_quote"].strip()}, now)
    return _inventory(load_state(project), inventory["id"])


def record_consent(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    entry = file_index(state).get(payload.get("file_id"))
    if entry is None or entry.get("origin") != "user_reference":
        raise ValidationError("Consent applies to a registered user reference.", field="file_id",
                              recovery="Send the id of the user's reference image.")
    problem = decision_problem(payload.get("user_quote"), CONFIRMATION_CUES)
    if problem:
        raise presentation_error("transmission_consent_missing", f"Consent was not given ({problem}).",
                                 "Ask whether the image may be sent to the image tool and record a clear yes.",
                                 field="user_quote")
    append_event(project, {"type": "transmission_consent", "file_id": entry["id"],
                           "user_quote": payload["user_quote"].strip()}, now)
    return file_index(load_state(project))[entry["id"]]


def _prompt(item: dict) -> str:
    observed = "; ".join(item["observed"]) or "no additional observations"
    return (
        f"Reconstruct ONLY the complete empty {item['name']} ({item['category']}) from the source crop. "
        "Exclude the wearer, body, skin, hair, mannequin, hanger, other layers, props, and scene. "
        "Lay it flat and centred on a pure white #FFFFFF square background with even padding, no shadow, "
        "no cropping. Preserve the exact colours, fabric texture, stitching, and pattern. "
        f"Observed details: {observed}. {POLICY_TEXT[item['graphic_policy']]} "
        "Prefer omission over invention: do not add pockets, fasteners, trims, hardware, or branding "
        "that the source does not show."
    )


def plan_extraction(project: Path, payload: dict) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    if not inventory.get("confirmed"):
        raise presentation_error("inventory_unconfirmed", "The user has not confirmed the garment list.",
                                 "Show the inventory and record the user's confirmation first.",
                                 field="inventory_id")
    source = file_index(state)[inventory["source_id"]]
    if source["origin"] == "user_reference" and not source.get("external_transmission_consent"):
        raise presentation_error("transmission_consent_missing",
                                 "The user has not agreed to send this image to the image tool.",
                                 "Ask once and record the reply with `extract` mode `consent`.",
                                 field="source_id")
    round_number = next_round(state, "extracted_garment", "inventory_id", inventory["id"])
    base = f"{FOLDER}{source['id']}/r{round_number:02d}"
    return {
        "inventory_id": inventory["id"],
        "round": round_number,
        "jobs": [
            {"slug": item["slug"], "prompt": _prompt(item), "inputs": [source["path"]], "crop": item["bbox"],
             "crop_padding": 0.12, "destination": f"{base}/{item['slug']}.png", "background": "#FFFFFF",
             "min_size": 1200, "aspect": "1:1"}
            for item in inventory["items"]
        ],
    }


def register_extraction(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    inventory = _inventory(state, payload.get("inventory_id"))
    round_number = payload.get("round")
    if not isinstance(round_number, int) or round_number < 1:
        raise ValidationError("Send the planned round number.", field="round",
                              recovery="Use `round` from the extraction plan.")
    items = {item["slug"]: item for item in inventory["items"]}
    files = file_index(state)
    source = files[inventory["source_id"]]
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("Send one result per rendered garment.", field="results",
                              recovery="Include slug, path, renderer, and prompt for each file.")
    timestamp = now or _utc_now()
    entries, seen_hashes = [], set()
    for result in results:
        item = items.get(result.get("slug"))
        if item is None:
            raise ValidationError("Result slug is not in the confirmed inventory.", field="slug",
                                  recovery="Use slugs from the confirmed inventory.")
        stem = f"{FOLDER}{source['id']}/r{round_number:02d}/{item['slug']}"
        path = result.get("path")
        if path not in (f"{stem}.png", f"{stem}.jpg", f"{stem}.jpeg"):
            raise ValidationError("Register the file at its planned destination.", field="path", path=path,
                                  recovery=f"Save the image as {stem}.png.")
        absolute, relative = check_image(project, path, FOLDER)
        digest = sha256(absolute)
        if digest in seen_hashes:
            raise ValidationError("Two results are byte-identical.", field="path", path=relative,
                                  recovery="Render each garment separately.")
        seen_hashes.add(digest)
        colours = garment_colours(absolute.read_bytes()) if absolute.suffix.lower() == ".png" else None
        colour_source = "measured"
        if colours is None:
            estimate = result.get("estimated_colours") or {}
            primary, secondary = estimate.get("primary"), estimate.get("secondary")
            if not isinstance(primary, str) or not HEX.match(primary) or (secondary is not None and not (
                    isinstance(secondary, str) and HEX.match(secondary))):
                raise ValidationError("Send estimated colours as #RRGGBB hex values.", field="estimated_colours",
                                      recovery="Estimate the garment's main colour, for example #1A2B3C.")
            colours, colour_source = {"primary": primary.upper(),
                                      "secondary": secondary.upper() if secondary else None}, "estimated"
        entry = {
            "id": f"xg-{inventory['id']}-r{round_number:02d}-{item['slug']}",
            "origin": "extracted_garment", "path": relative, "sha256": digest, "parents": [source["id"]],
            "registered_at": timestamp, "production_eligible": False, "inventory_id": inventory["id"],
            "round": round_number, "slug": item["slug"], "name": item["name"], "category": item["category"],
            "details": item["details"], "primary_colour": colours["primary"],
            "secondary_colour": colours["secondary"], "colour_source": colour_source,
            "renderer": str(result.get("renderer") or "unknown"), "prompt": str(result.get("prompt") or ""),
            "untrusted_text": True,
        }
        entry["listing_eligible"] = listing_eligible(entry, files)
        entries.append(entry)
    register_entries(project, entries, timestamp)
    catalogue = render_catalogue(project)
    return {"entries": entries, "catalogue": catalogue.relative_to(project).as_posix()}


def render_catalogue(project: Path) -> Path:
    state = load_state(project)
    garments = [item for item in state.get("files", []) if item.get("origin") == "extracted_garment"]
    esc = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    tabs = "".join(f'<a href="#{c}">{c.upper()}</a>' for c in ("all", *CATEGORIES))
    cards = []
    for item in garments:
        image = Path(item["path"]).relative_to("presentation/extracted").as_posix()
        swatches = "".join(
            f'<span class="swatch" style="background:{colour}"></span><code>{colour}</code>'
            for colour in (item.get("primary_colour"), item.get("secondary_colour"))
            if isinstance(colour, str) and HEX.match(colour)
        )
        tags = "".join(f"<li>{esc(tag)}</li>" for tag in item.get("details", []))
        cards.append(
            f'<figure class="card {esc(item["category"])}"><img src="{esc(image)}" alt="{esc(item["name"])}">'
            f'<figcaption><strong>{esc(item["name"])}</strong><span>{esc(item["category"])}</span>'
            f'<div>{swatches}</div><ul>{tags}</ul>'
            f'<small>{"listing-eligible" if item.get("listing_eligible") else "inspiration only"}</small>'
            "</figcaption></figure>"
        )
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Catalogue</title><style>"
        "body{font-family:Helvetica,Arial,sans-serif;background:#F4F2EC;margin:32px;color:#1A1A1A}"
        "nav a{border:1px solid #CCC;padding:8px 14px;margin-right:4px;text-decoration:none;color:#1A1A1A}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:24px;margin-top:24px}"
        ".card{margin:0;background:#FFF;padding:12px}.card img{width:100%;aspect-ratio:1;object-fit:contain}"
        ".swatch{display:inline-block;width:14px;height:14px;border:1px solid #999;margin-right:4px}"
        "ul{padding:0;list-style:none}li{display:inline-block;border:1px solid #CCC;padding:2px 6px;margin:2px}"
        f"</style></head><body><p>{len(garments)} PIECES</p><nav>{tabs}</nav>"
        f"<main class=\"grid\">{''.join(cards)}</main></body></html>\n"
    )
    target = project / FOLDER / "catalogue.html"
    write_atomic(target, page.encode("utf-8"))
    return target
```

`catalogue.html` is a regenerated view and is not registered, so `validate` ignores it. The spec's `consent` and `confirm` steps are the modes `consent` and `confirm`. The spec text "recorded with `register_file`" is satisfied by recording consent against the registered reference.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_extract
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio_core/extract.py tests/test_extract.py
git commit -m "feat: extract garments into white-background catalogue cut-outs"
```

---

### Task 4: AI model library (`create_models`, defaults, pinning)

**Files:**
- Create: `scripts/studio_core/models.py`, `assets/models/{m-aria,m-kai,m-noor,m-theo}/identity.json`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes (Task 1): `library_root`, `check_image`, `sha256`, `presentation_error`, `record_decision`, `kept_ids`, `register_entries`, `next_round`, `file_index`, `PRESENTATION_FOLDERS`.
- Produces:
  - `IDENTITY_KEYS: tuple[str, ...]`
  - `validate_identity(card: dict) -> dict`
  - `refuse_real_person(*texts: str) -> None`
  - `install_defaults(project: Path, bundle_dir: Path) -> dict`, returning `{"installed": [...], "missing_images": [...]}`
  - `library_models(project: Path) -> dict[str, dict]`, mapping id to identity plus `"front_image": str | None`
  - `plan_models(project: Path, payload: dict) -> dict`
  - `plan_reference(project: Path, payload: dict) -> dict`
  - `register_models(project: Path, payload: dict, now: str | None = None) -> list[dict]`
  - `keep_models(project: Path, payload: dict, now: str | None = None) -> dict`
  - `pin_model(project: Path, model_id: str, now: str | None = None) -> dict`, returning the project `synthetic_model` entry, pinned by hash

- [ ] **Step 1: Write the four default identity cards**

Each card is a JSON file with every key in `IDENTITY_KEYS`. For example, `assets/models/m-aria/identity.json`:

```json
{
  "id": "m-aria",
  "display_name": "Aria",
  "gender_presentation": "feminine",
  "age_range": "22-28",
  "build": "slim, 170 cm impression",
  "height_impression": "tall",
  "skin_tone": "light olive",
  "hair": "shoulder-length straight dark brown hair, tucked behind ears",
  "face_description": "oval face, neutral relaxed expression, no makeup look, no jewellery",
  "neutral_outfit": "plain white fitted crew tee and straight black trousers",
  "lighting": "soft even studio light from front-left, no harsh shadows",
  "camera": "full-length, eye level, 50mm equivalent, centred",
  "background": "plain warm-grey studio backdrop #E9E6DF",
  "ai_generated_person": true,
  "renderer": "unrendered",
  "prompt": "Photorealistic AI-generated fictional fashion model, not based on any real person."
}
```

The other three follow the same shape:
- `m-kai`: masculine, 20-26, athletic, medium brown skin, short textured black hair.
- `m-noor`: androgynous, 25-32, average build, deep brown skin, close-cropped curls.
- `m-theo`: masculine, 30-38, broad, fair skin, short wavy auburn hair.

Each has the same neutral outfit, lighting, camera, and background, `"ai_generated_person": true`, and `"renderer": "unrendered"`.

No reference images ship, because none was generated at build time. `install_defaults` reports them as `missing_images`.

- [ ] **Step 2: Write the failing tests**

`tests/test_models.py`:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.models import (
    install_defaults,
    keep_models,
    library_models,
    pin_model,
    plan_models,
    plan_reference,
    refuse_real_person,
    register_models,
)
from scripts.studio_core.store import load_state
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW, make_png, make_project

BUNDLE = Path(__file__).resolve().parents[1]
PIXEL = (120, 100, 90, 255)


def png(seed: int) -> bytes:
    return make_png(2, 2, [[(seed, 10, 10, 255), PIXEL], [PIXEL, PIXEL]])


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = make_project(Path(self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    def render(self, job, data):
        target = self.project / job["destination"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"label": job.get("label"), "model_id": job.get("model_id"), "path": job["destination"],
                "renderer": "host-image-tool", "prompt": job["prompt"]}

    def test_defaults_install_once_outside_the_skill(self):
        result = install_defaults(self.project, BUNDLE)
        self.assertEqual(sorted(result["installed"]), ["m-aria", "m-kai", "m-noor", "m-theo"])
        self.assertEqual(sorted(result["missing_images"]), ["m-aria", "m-kai", "m-noor", "m-theo"])
        self.assertEqual(install_defaults(self.project, BUNDLE)["installed"], [])
        self.assertFalse(any(BUNDLE.rglob("front.png")))

    def test_real_person_backstop(self):
        for text in ("looks like Zendaya", "celebrity lookalike", "resembling a famous influencer"):
            with self.subTest(text=text), self.assertRaises(ValidationError) as caught:
                refuse_real_person(text)
            self.assertEqual(caught.exception.details[0]["code"], "real_person_model_refused")
        refuse_real_person("athletic build, short black hair")

    def test_candidates_need_affirmative_keep(self):
        plan = plan_models(self.project, {"range": {"gender_presentation": "feminine", "age_range": "20-30",
                                                     "build": "varied", "skin_tone": "varied", "hair": "varied"}})
        self.assertEqual([job["label"] for job in plan["jobs"]], ["A", "B", "C", "W"])
        results = [self.render(job, png(index)) for index, job in enumerate(plan["jobs"])]
        entries = register_models(self.project, {"kind": "candidates", "round": plan["round"],
                                                 "results": results, "identities": plan["identities"]}, FIXED_NOW)
        with self.assertRaises(ValidationError):
            keep_models(self.project, {"ids": [entries[0]["id"]], "user_quote": "maybe"}, FIXED_NOW)
        kept = keep_models(self.project, {"ids": [entries[0]["id"]], "user_quote": "Keep A, yes"}, FIXED_NOW)
        self.assertIn(kept["models"][0], library_models(self.project))
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_reference_render_for_default_then_pin_by_hash(self):
        install_defaults(self.project, BUNDLE)
        job = plan_reference(self.project, {"model_id": "m-kai"})["jobs"][0]
        register_models(self.project, {"kind": "reference", "results": [self.render(job, png(7))]}, FIXED_NOW)
        self.assertIsNotNone(library_models(self.project)["m-kai"]["front_image"])
        entry = pin_model(self.project, "m-kai", FIXED_NOW)
        self.assertEqual(entry["origin"], "synthetic_model")
        self.assertTrue(entry["ai_generated_person"])
        self.assertEqual(pin_model(self.project, "m-kai", FIXED_NOW)["id"], entry["id"])
        (self.project.parent / "_models/m-kai/front.png").write_bytes(png(99))
        self.assertEqual(validate_project(self.project)["errors"], [])
        self.assertTrue((self.project / entry["path"]).read_bytes() != png(99))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_models
```

Expected: `ModuleNotFoundError: scripts.studio_core.models`.

- [ ] **Step 4: Implement `scripts/studio_core/models.py`**

```python
"""AI-generated model library: identity cards, defaults, candidates, and per-project pinning.

Models are fictional people generated by the host image tool. Real people, lookalikes,
and photos of real people are refused. Projects pin a copy of the model image and its
hash, so later library changes never alter an existing try-on.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .config import ensure_external
from .errors import ValidationError
from .presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    file_index,
    kept_ids,
    library_root,
    next_round,
    presentation_error,
    record_decision,
    register_entries,
    sha256,
)
from .store import _utc_now, load_state, write_atomic

IDENTITY_KEYS = (
    "id", "display_name", "gender_presentation", "age_range", "build", "height_impression", "skin_tone",
    "hair", "face_description", "neutral_outfit", "lighting", "camera", "background",
)
RANGE_KEYS = ("gender_presentation", "age_range", "build", "skin_tone", "hair")
MODEL_ID = re.compile(r"^m-[a-z0-9-]{1,40}$")
REAL_PERSON = re.compile(
    r"\b(?:celebrit\w*|look[- ]?alike|looks?\s+like|resembl\w*|influencer|famous|actor|actress|singer|athlete"
    r"|in\s+the\s+style\s+of|real\s+person|photo\s+of\s+(?:me|my|a\s+friend))\b",
    re.IGNORECASE,
)
FOLDER = PRESENTATION_FOLDERS["synthetic_model"]
LABELS = ("A", "B", "C", "W")
NO_REAL_PERSON = "Fictional AI-generated fashion model, not based on or resembling any real person."


def refuse_real_person(*texts: str) -> None:
    for text in texts:
        if isinstance(text, str) and REAL_PERSON.search(text):
            raise presentation_error("real_person_model_refused",
                                     "Models must be fictional; real people and lookalikes are refused.",
                                     "Describe the model by build, age range, skin tone, and hair only.")


def validate_identity(card: dict) -> dict:
    if not isinstance(card, dict):
        raise ValidationError("Identity card must be an object.", field="identity", recovery="Send a JSON object.")
    missing = [key for key in IDENTITY_KEYS if not isinstance(card.get(key), str) or not card[key].strip()]
    if missing or not MODEL_ID.match(card.get("id", "")):
        raise ValidationError(f"Identity card is incomplete: {', '.join(missing) or 'id'}.", field="identity",
                              recovery="Fill every identity field; ids look like `m-aria`.")
    refuse_real_person(*(card[key] for key in IDENTITY_KEYS))
    return {**{key: card[key].strip() for key in IDENTITY_KEYS}, "ai_generated_person": True,
            "renderer": str(card.get("renderer") or "unrendered"), "prompt": str(card.get("prompt") or NO_REAL_PERSON)}


def _library(project: Path) -> Path:
    root = library_root(project)
    ensure_external(root.parent, Path(__file__).resolve().parents[2])
    return root


def library_models(project: Path) -> dict[str, dict]:
    root = library_root(project)
    models = {}
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            card = folder / "identity.json"
            if card.is_file():
                identity = json.loads(card.read_text("utf-8"))
                front = folder / "front.png"
                identity["front_image"] = str(front) if front.is_file() else None
                models[identity["id"]] = identity
    return models


def install_defaults(project: Path, bundle_dir: Path) -> dict:
    root = _library(project)
    installed, missing = [], []
    for folder in sorted((Path(bundle_dir) / "assets/models").iterdir()):
        card = validate_identity(json.loads((folder / "identity.json").read_text("utf-8")))
        target = root / card["id"]
        if not (target / "identity.json").exists():
            write_atomic(target / "identity.json", (json.dumps(card, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            if (folder / "front.png").is_file():
                shutil.copyfile(folder / "front.png", target / "front.png")
            installed.append(card["id"])
        if not (target / "front.png").is_file():
            missing.append(card["id"])
    return {"installed": installed, "missing_images": missing, "library": str(root)}


def _model_prompt(card: dict) -> str:
    return (f"{NO_REAL_PERSON} {card['gender_presentation']}, age {card['age_range']}, {card['build']}, "
            f"{card['height_impression']}, {card['skin_tone']} skin, {card['hair']}, {card['face_description']}. "
            f"Wearing {card['neutral_outfit']}. {card['lighting']}. {card['camera']}. {card['background']}. "
            "Front view, standing straight, arms relaxed at sides.")


def plan_models(project: Path, payload: dict) -> dict:
    spec = payload.get("range")
    if not isinstance(spec, dict) or any(not isinstance(spec.get(key), str) or not spec[key].strip()
                                         for key in RANGE_KEYS):
        raise ValidationError(f"Describe the model range with: {', '.join(RANGE_KEYS)}.", field="range",
                              recovery="Ask the user for gender presentation, age range, build, skin tone, and hair.")
    refuse_real_person(*spec.values())
    state = load_state(project)
    round_number = next_round(state, "synthetic_model", "kind", "candidate")
    jobs, identities = [], {}
    for label in LABELS:
        identity = validate_identity({
            "id": f"m-r{round_number:02d}-{label.lower()}", "display_name": f"Candidate {label}",
            "gender_presentation": spec["gender_presentation"], "age_range": spec["age_range"],
            "build": spec["build"], "height_impression": "average", "skin_tone": spec["skin_tone"],
            "hair": spec["hair"], "face_description": f"distinct face {label}, neutral expression",
            "neutral_outfit": "plain white fitted crew tee and straight black trousers",
            "lighting": "soft even studio light", "camera": "full-length, eye level, centred",
            "background": "plain warm-grey studio backdrop #E9E6DF",
        })
        identities[label] = identity
        jobs.append({"label": label, "prompt": _model_prompt(identity) + (
            " Vary one visible trait from the other candidates." if label == "W" else ""),
            "destination": f"{FOLDER}candidates/r{round_number:02d}/model-{label}.png", "aspect": "3:4"})
    return {"round": round_number, "jobs": jobs, "identities": identities}


def plan_reference(project: Path, payload: dict) -> dict:
    model = library_models(project).get(payload.get("model_id"))
    if model is None:
        raise presentation_error("model_not_kept", "That model is not in the library.",
                                 "Install defaults or keep a candidate first.", field="model_id")
    return {"jobs": [{"model_id": model["id"], "prompt": _model_prompt(model),
                      "destination": f"{FOLDER}references/{model['id']}-front.png", "aspect": "3:4"}]}


def register_models(project: Path, payload: dict, now: str | None = None) -> list[dict]:
    kind = payload.get("kind")
    timestamp = now or _utc_now()
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("Send the rendered model images.", field="results", recovery="Include path and prompt.")
    entries = []
    if kind == "candidates":
        identities = payload.get("identities") or {}
        round_number = payload.get("round")
        for result in results:
            label = result.get("label")
            expected = f"{FOLDER}candidates/r{round_number:02d}/model-{label}.png"
            if label not in LABELS or result.get("path") != expected:
                raise ValidationError("Register candidates at their planned destinations.", field="path",
                                      recovery=f"Save candidate {label} as {expected}.")
            absolute, relative = check_image(project, result["path"], FOLDER)
            identity = validate_identity(identities.get(label) or {})
            entries.append({"id": identity["id"], "origin": "synthetic_model", "path": relative,
                            "sha256": sha256(absolute), "parents": [], "registered_at": timestamp,
                            "production_eligible": False, "kind": "candidate", "round": round_number,
                            "ai_generated_person": True, "identity": identity,
                            "renderer": str(result.get("renderer") or "unknown")})
        register_entries(project, entries, timestamp)
        return entries
    if kind == "reference":
        library = library_models(project)
        for result in results:
            model = library.get(result.get("model_id"))
            expected = f"{FOLDER}references/{result.get('model_id')}-front.png"
            if model is None or result.get("path") != expected:
                raise ValidationError("Register the reference at its planned destination.", field="path",
                                      recovery=f"Save it as {expected}.")
            absolute, _ = check_image(project, result["path"], FOLDER)
            shutil.copyfile(absolute, library_root(project) / model["id"] / "front.png")
            entries.append({"model_id": model["id"], "library_image": str(library_root(project) / model["id"])})
        return entries
    raise ValidationError("Kind must be `candidates` or `reference`.", field="kind",
                          recovery="Use the kind returned by the plan.")


def keep_models(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    files = file_index(state)
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids or any(files.get(i, {}).get("kind") != "candidate" for i in ids):
        raise ValidationError("Keep registered model candidates only.", field="ids",
                              recovery="Send ids returned by `create_models` register.")
    record_decision(project, "model", ids, "keep", payload.get("user_quote"), now)
    root = _library(project)
    for model_id in ids:
        entry = files[model_id]
        target = root / model_id
        write_atomic(target / "identity.json",
                     (json.dumps({**entry["identity"], "renderer": entry["renderer"]}, indent=2, sort_keys=True)
                      + "\n").encode("utf-8"))
        shutil.copyfile(project / entry["path"], target / "front.png")
    return {"models": ids, "library": str(root)}


def pin_model(project: Path, model_id: str, now: str | None = None) -> dict:
    state = load_state(project)
    for entry in state.get("files", []):
        if entry.get("origin") == "synthetic_model" and entry.get("library_model_id") == model_id:
            return entry
    model = library_models(project).get(model_id)
    kept_candidate = model_id in kept_ids(state, "model")
    if model is None or not model.get("front_image"):
        raise presentation_error("model_not_kept",
                                 "That model is not in the library or has no reference image yet.",
                                 "Keep a candidate, or run `create_models` mode `plan_reference` for a default.",
                                 field="model_id")
    relative = f"{FOLDER}pinned/{model_id}-front.png"
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(model["front_image"], target)
    timestamp = now or _utc_now()
    entry = {"id": f"pin-{model_id}", "origin": "synthetic_model", "path": relative, "sha256": sha256(target),
             "parents": [], "registered_at": timestamp, "production_eligible": False, "kind": "pinned",
             "library_model_id": model_id, "ai_generated_person": True, "kept_candidate": kept_candidate,
             "identity": validate_identity({key: model[key] for key in IDENTITY_KEYS})}
    register_entries(project, [entry], timestamp)
    return entry
```

- [ ] **Step 5: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_models
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK` for both.

- [ ] **Step 6: Commit**

```bash
git add scripts/studio_core/models.py assets/models tests/test_models.py
git commit -m "feat: add AI model library with defaults, keep decisions, and pinning"
```

---

### Task 5: `try_on`

**Files:**
- Create: `scripts/studio_core/tryon.py`
- Test: `tests/test_tryon.py`

**Interfaces:**
- Consumes (Task 1): `check_image`, `file_index`, `listing_eligible`, `kept_ids`, `presentation_error`, `register_entries`, `record_decision`, `next_round`, `sha256`.
- Consumes (Task 4): `pin_model(project, model_id, now) -> dict`.
- Produces:
  - `POSES = ("front", "three_quarter", "back")`
  - `plan_tryon(project: Path, payload: dict, now: str | None = None) -> dict`, returning `{"round", "model", "identity_lock", "jobs": [...]}`
  - `register_tryon(project: Path, payload: dict, now: str | None = None) -> list[dict]`
  - `decide_tryon(project: Path, payload: dict, now: str | None = None) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_tryon.py`:

```python
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.models import install_defaults, plan_reference, register_models
from scripts.studio_core.presentation import kept_ids
from scripts.studio_core.store import load_state
from scripts.studio_core.tryon import decide_tryon, plan_tryon, register_tryon
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW, make_png, ready_project
from tests.test_extract import GARMENT, ITEM

BUNDLE = Path(__file__).resolve().parents[1]


def png(seed):
    return make_png(2, 1, [[(seed, 0, 0, 255), (0, seed, 0, 255)]])


class TryOnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = ready_project(Path(self.temp.name))
        install_defaults(self.project, BUNDLE)
        job = plan_reference(self.project, {"model_id": "m-aria"})["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(9))
        register_models(self.project, {"kind": "reference", "results": [
            {"model_id": "m-aria", "path": job["destination"], "prompt": job["prompt"]}]}, FIXED_NOW)
        self.design = next(item["id"] for item in load_state(self.project)["files"]
                           if item["origin"] == "approved_design" and item.get("role") != "review_evidence")

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_pins_model_and_locks_identity(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria",
                                         "poses": ["front", "back"]}, FIXED_NOW)
        self.assertEqual([job["pose"] for job in plan["jobs"]], ["front", "back"])
        job = plan["jobs"][0]
        self.assertIn("presentation/models/pinned/m-aria-front.png", job["inputs"])
        self.assertIn("exactly as shown", job["prompt"])
        self.assertIn("same person", job["prompt"])
        self.assertEqual(job["destination"], "presentation/tryon/r01/m-aria-front.png")

    def test_plan_refuses_bad_poses_models_and_ineligible_garments(self):
        with self.assertRaises(ValidationError):
            plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["side"]}, FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_tryon(self.project, {"design_id": self.design, "model_id": "m-nobody", "poses": ["front"]}, FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "model_not_kept")
        ineligible = {"id": "xg-shop", "origin": "extracted_garment", "listing_eligible": False}
        from scripts.studio_core.presentation import register_entries
        path = self.project / "presentation/extracted/shop/r01/x.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(GARMENT)
        import hashlib
        register_entries(self.project, [{**ineligible, "path": "presentation/extracted/shop/r01/x.png",
                                         "sha256": hashlib.sha256(GARMENT).hexdigest(),
                                         "parents": ["ref-missing"], "registered_at": FIXED_NOW,
                                         "production_eligible": False}], FIXED_NOW)
        with self.assertRaises(ValidationError) as caught:
            plan_tryon(self.project, {"garment_ids": ["xg-shop"], "model_id": "m-aria", "poses": ["front"]}, FIXED_NOW)
        self.assertEqual(caught.exception.details[0]["code"], "garment_not_listing_eligible")

    def test_register_and_keep(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["front"]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(3))
        entries = register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria",
                                                "garment_ids": [self.design], "results": [
            {"pose": "front", "path": job["destination"], "renderer": "host", "prompt": job["prompt"]}]}, FIXED_NOW)
        entry = entries[0]
        self.assertEqual(entry["label"], "AI try-on")
        self.assertEqual(entry["parents"], [self.design, "pin-m-aria"])
        with self.assertRaises(ValidationError):
            decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep",
                                        "user_quote": "Keep, but fix the collar"}, FIXED_NOW)
        decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep", "user_quote": "Yes keep it"}, FIXED_NOW)
        self.assertEqual(kept_ids(load_state(self.project), "tryon"), {entry["id"]})
        self.assertEqual(validate_project(self.project)["errors"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_tryon
```

Expected: `ModuleNotFoundError: scripts.studio_core.tryon`.

- [ ] **Step 3: Implement `scripts/studio_core/tryon.py`**

```python
"""Put approved designs or eligible cut-outs on a pinned AI model."""

from __future__ import annotations

from pathlib import Path

from .errors import ValidationError
from .models import pin_model
from .presentation import (
    PRESENTATION_FOLDERS,
    check_image,
    file_index,
    listing_eligible,
    next_round,
    presentation_error,
    record_decision,
    register_entries,
    sha256,
)
from .store import _utc_now, load_state

POSES = ("front", "three_quarter", "back")
FOLDER = PRESENTATION_FOLDERS["tryon_image"]
POSE_TEXT = {"front": "front view", "three_quarter": "three-quarter view turned 45 degrees", "back": "back view"}


def _garments(state: dict, payload: dict) -> list[dict]:
    files = file_index(state)
    ids = payload.get("garment_ids") or ([payload["design_id"]] if payload.get("design_id") else [])
    if not ids:
        raise ValidationError("Choose an approved design or extracted garments.", field="garment_ids",
                              recovery="Send `design_id` or `garment_ids`.")
    garments = []
    for garment_id in ids:
        entry = files.get(garment_id)
        if entry is None or entry.get("origin") not in {"approved_design", "extracted_garment"} \
                or entry.get("role") == "review_evidence":
            raise ValidationError(f"`{garment_id}` is not an approved design or extracted garment.",
                                  field="garment_ids", recovery="Use ids from approvals or `extract`.")
        if not listing_eligible(entry, files) or entry.get("listing_eligible") is False:
            raise presentation_error("garment_not_listing_eligible",
                                     f"`{garment_id}` comes from a third-party or unconfirmed source.",
                                     "Use your own approved design or a cut-out from an image you own.",
                                     field="garment_ids")
        garments.append(entry)
    return garments


def plan_tryon(project: Path, payload: dict, now: str | None = None) -> dict:
    poses = payload.get("poses")
    if not isinstance(poses, list) or not poses or any(pose not in POSES for pose in poses) \
            or len(set(poses)) != len(poses):
        raise ValidationError(f"Poses must be distinct values from: {', '.join(POSES)}.", field="poses",
                              recovery="Choose front, three_quarter, and/or back.")
    garments = _garments(load_state(project), payload)
    model = pin_model(project, payload.get("model_id"), now)
    identity = model["identity"]
    state = load_state(project)
    round_number = next_round(state, "tryon_image", "model_id", identity["id"])
    anchors = "; ".join(f"{key}: {identity[key]}" for key in (
        "gender_presentation", "age_range", "build", "skin_tone", "hair", "face_description", "lighting", "camera",
        "background"))
    garment_text = ", ".join(entry.get("name") or Path(entry["path"]).stem for entry in garments)
    jobs = [{
        "pose": pose,
        "inputs": [model["path"], *(entry["path"] for entry in garments)],
        "prompt": (f"Show the same person as the model reference image ({anchors}) wearing {garment_text}, "
                   f"{POSE_TEXT[pose]}, full length. Keep every identity anchor unchanged. Reproduce the garment "
                   "exactly as shown: same colour, print, placement, and scale; no invented logos, pockets, "
                   "or trims. Fictional AI-generated model; not any real person."),
        "destination": f"{FOLDER}r{round_number:02d}/{identity['id']}-{pose}.png",
        "aspect": "3:4",
    } for pose in poses]
    return {"round": round_number, "model": model["id"], "identity_lock": "reference_image", "jobs": jobs}


def register_tryon(project: Path, payload: dict, now: str | None = None) -> list[dict]:
    state = load_state(project)
    garments = _garments(state, payload)
    files = file_index(state)
    model = files.get(f"pin-{payload.get('model_id')}")
    if model is None:
        raise presentation_error("model_not_kept", "Plan the try-on first so the model is pinned.",
                                 "Run `try_on` mode `plan`.", field="model_id")
    round_number, timestamp = payload.get("round"), now or _utc_now()
    entries = []
    for result in payload.get("results") or []:
        pose = result.get("pose")
        expected = f"{FOLDER}r{round_number:02d}/{model['library_model_id']}-{pose}.png"
        if pose not in POSES or result.get("path") != expected:
            raise ValidationError("Register each try-on at its planned destination.", field="path",
                                  recovery=f"Save the {pose} image as {expected}.")
        absolute, relative = check_image(project, result["path"], FOLDER)
        entries.append({"id": f"try-{model['library_model_id']}-r{round_number:02d}-{pose}", "origin": "tryon_image",
                        "path": relative, "sha256": sha256(absolute),
                        "parents": [*(entry["id"] for entry in garments), model["id"]], "registered_at": timestamp,
                        "production_eligible": False, "label": "AI try-on", "pose": pose, "round": round_number,
                        "model_id": model["library_model_id"], "renderer": str(result.get("renderer") or "unknown"),
                        "prompt": str(result.get("prompt") or "")})
    if not entries:
        raise ValidationError("Send the rendered try-on images.", field="results", recovery="Include pose and path.")
    register_entries(project, entries, timestamp)
    return entries


def decide_tryon(project: Path, payload: dict, now: str | None = None) -> dict:
    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if any(files.get(item, {}).get("origin") != "tryon_image" for item in ids):
        raise ValidationError("Decide on registered try-on images only.", field="ids",
                              recovery="Use ids returned by `try_on` register.")
    return record_decision(project, "tryon", ids, payload.get("decision"), payload.get("user_quote"), now)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_tryon
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio_core/tryon.py tests/test_tryon.py
git commit -m "feat: add try-on planning and registration on pinned AI models"
```

---

### Task 6: `create_listing` (listing concept page)

**Files:**
- Create: `scripts/studio_core/listing.py`
- Test: `tests/test_listing.py`

**Interfaces:**
- Consumes: `file_index`, `kept_ids`, `listing_eligible`, `record_decision`, `register_entries`, `sha256`, `PRESENTATION_FOLDERS`; `store.append_event`, `load_state`, `write_atomic`.
- Produces:
  - `SLOTS = ("hero", "white_background", "front", "three_quarter", "back")`
  - `build_listing(project: Path, payload: dict, now: str | None = None) -> dict`, returning `{"version", "files", "slots", "missing"}`
  - `decide_listing(project: Path, payload: dict, now: str | None = None) -> dict`

- [ ] **Step 1: Write the failing tests**

`tests/test_listing.py`:

```python
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # discoverable from any cwd

from scripts.studio_core.errors import ValidationError
from scripts.studio_core.listing import build_listing, decide_listing
from scripts.studio_core.store import load_state
from scripts.studio_core.tryon import decide_tryon, plan_tryon, register_tryon
from scripts.studio_core.validation import validate_project
from tests.helpers import FIXED_NOW
from tests.test_tryon import TryOnTests, png


class ListingTests(TryOnTests):
    def kept_tryon(self, pose="front"):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": [pose]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(40 + len(pose)))
        entry = register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria",
                                              "garment_ids": [self.design],
                                              "results": [{"pose": pose, "path": job["destination"]}]}, FIXED_NOW)[0]
        decide_tryon(self.project, {"ids": [entry["id"]], "decision": "keep", "user_quote": "Yes"}, FIXED_NOW)
        return entry

    def test_listing_has_no_unconfirmed_text_and_marks_missing_slots(self):
        tryon = self.kept_tryon("front")
        result = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertEqual(result["version"], "listing-v001")
        self.assertEqual(result["slots"]["front"], tryon["id"])
        self.assertIn("back", result["missing"])
        self.assertIn("white_background", result["missing"])
        page = (self.project / result["files"]["html"]).read_text("utf-8")
        self.assertIn("Concept — not a live listing", page)
        for banned in ("¥", "$", "SGD", "RMB", "price", "Price", "size chart", "cm"):
            self.assertNotIn(banned, re.sub(r"<style>.*?</style>", "", page, flags=re.S))
        self.assertEqual(validate_project(self.project)["errors"], [])

    def test_unkept_or_ineligible_images_are_excluded(self):
        plan = plan_tryon(self.project, {"design_id": self.design, "model_id": "m-aria", "poses": ["back"]}, FIXED_NOW)
        job = plan["jobs"][0]
        (self.project / job["destination"]).parent.mkdir(parents=True, exist_ok=True)
        (self.project / job["destination"]).write_bytes(png(77))
        register_tryon(self.project, {"round": plan["round"], "model_id": "m-aria", "garment_ids": [self.design],
                                      "results": [{"pose": "back", "path": job["destination"]}]}, FIXED_NOW)
        result = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertIsNone(result["slots"]["back"])

    def test_design_name_is_escaped_and_versions_increment(self):
        self.kept_tryon("front")
        first = build_listing(self.project, {"version": "v001", "design_name": "<img src=x onerror=1>"}, FIXED_NOW)
        page = (self.project / first["files"]["html"]).read_text("utf-8")
        self.assertNotIn("<img src=x", page)
        second = build_listing(self.project, {"version": "v001"}, FIXED_NOW)
        self.assertEqual(second["version"], "listing-v002")
        with self.assertRaises(ValidationError):
            decide_listing(self.project, {"ids": [first["files"]["html_id"]], "decision": "keep",
                                          "user_quote": "Keep for now"}, FIXED_NOW)

    def test_unknown_approval_version_is_refused(self):
        with self.assertRaises(ValidationError):
            build_listing(self.project, {"version": "v404"}, FIXED_NOW)


if __name__ == "__main__":
    unittest.main()
```

Because `ListingTests` subclasses `TryOnTests`, it reuses the setup and also re-runs the try-on tests. That is intended.

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_listing
```

Expected: `ModuleNotFoundError: scripts.studio_core.listing`.

- [ ] **Step 3: Implement `scripts/studio_core/listing.py`**

```python
"""Taobao-style listing concept: a visual mock that carries no unconfirmed facts."""

from __future__ import annotations

import html
import os
from pathlib import Path

from .errors import ValidationError
from .presentation import (
    PRESENTATION_FOLDERS,
    file_index,
    kept_ids,
    listing_eligible,
    record_decision,
    register_entries,
    sha256,
)
from .store import _utc_now, append_event, load_state, write_atomic

SLOTS = ("hero", "white_background", "front", "three_quarter", "back")
FOLDER = PRESENTATION_FOLDERS["listing_concept"]
TAG = "Concept — not a live listing"


def _pick(state: dict, version: str) -> dict:
    files = file_index(state)
    approved = [item for item in state.get("files", []) if item.get("origin") == "approved_design"
                and item.get("version") == version and item.get("role") != "review_evidence"]
    design_ids = {item["id"] for item in approved}
    kept = kept_ids(state, "tryon") | kept_ids(state, "garment")
    slots = dict.fromkeys(SLOTS)
    for entry in state.get("files", []):
        if entry["id"] not in kept or not listing_eligible(entry, files):
            continue
        if entry["origin"] == "tryon_image" and design_ids & set(entry["parents"]) and slots[entry["pose"]] is None:
            slots[entry["pose"]] = entry["id"]
        if entry["origin"] == "extracted_garment" and slots["white_background"] is None:
            slots["white_background"] = entry["id"]
    slots["hero"] = slots["front"] or slots["three_quarter"]
    return slots


def build_listing(project: Path, payload: dict, now: str | None = None) -> dict:
    state = load_state(project)
    version = payload.get("version")
    if version not in {item["version"] for item in state.get("approvals", [])}:
        raise ValidationError("Build a listing concept from a recorded approved version.", field="version",
                              recovery="Send an approved version such as v001.")
    files = file_index(state)
    slots = _pick(state, version)
    number = 1 + len(state.get("presentation", {}).get("listings", []))
    folder = f"{FOLDER}v{number:03d}"
    out = project / folder
    name = html.escape(str(payload.get("design_name") or state["project_name"]), quote=True)

    def src(slot: str) -> str | None:
        entry = files.get(slots[slot]) if slots[slot] else None
        return html.escape(os.path.relpath(project / entry["path"], out), quote=True) if entry else None

    def frame(slot: str, size: str) -> str:
        image = src(slot)
        label = slot.replace("_", " ")
        return (f'<figure class="slot {size}"><img src="{image}" alt="{label}"></figure>' if image
                else f'<figure class="slot {size} empty"><figcaption>{label} — not generated yet</figcaption></figure>')

    bars = '<div class="bar w80"></div><div class="bar w40"></div><div class="bar w60"></div>'
    closeups = "".join(
        f'<figure class="crop" style="background-image:url(\'{src("white_background")}\');'
        f'background-position:{pos}"></figure>' for pos in ("20% 20%", "50% 50%", "80% 70%")
    ) if src("white_background") else ""
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Listing concept</title><style>"
        "body{margin:0;background:#EEE;font-family:Helvetica,Arial,sans-serif;color:#1A1A1A}"
        ".page{width:750px;margin:0 auto;background:#FFF}.tag{background:#1A1A1A;color:#FFF;font-size:12px;padding:6px 12px}"
        ".gallery{display:grid;grid-template-columns:repeat(4,1fr);gap:4px}.slot{margin:0;aspect-ratio:1;background:#F4F4F4}"
        ".slot.main{grid-column:1/-1}.slot img{width:100%;height:100%;object-fit:cover}"
        ".empty{display:flex;align-items:center;justify-content:center;border:2px dashed #BBB;color:#888}"
        ".bar{height:14px;background:#DDD;margin:10px 16px;border-radius:4px}.w80{width:80%}.w40{width:40%}.w60{width:60%}"
        ".crop{margin:4px 0;height:260px;background-size:300%}"
        f"</style></head><body><div class=\"page\"><div class=\"tag\">{TAG}</div>"
        f"<section class=\"gallery\">{frame('hero', 'main')}"
        f"{''.join(frame(slot, 'thumb') for slot in SLOTS[1:])}</section>"
        f"<h1 style=\"font-size:20px;margin:16px\">{name}</h1>{bars}"
        f"<section class=\"detail\">{frame('front', 'full')}{closeups}</section></div></body></html>\n"
    )
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="750" height="900"><rect width="750" height="900" fill="#FFF"/>'
           f'<rect width="750" height="28" fill="#1A1A1A"/><text x="12" y="19" fill="#FFF" font-size="12" '
           f'font-family="Helvetica">{TAG}</text>'
           + (f'<image href="{src("hero")}" x="0" y="28" width="750" height="750" '
              'preserveAspectRatio="xMidYMid slice"/>' if src("hero")
              else '<rect x="0" y="28" width="750" height="750" fill="#F4F4F4" stroke="#BBB" stroke-dasharray="8"/>')
           + f'<text x="16" y="820" font-size="20" font-family="Helvetica">{name}</text>'
           '<rect x="16" y="840" width="600" height="14" rx="4" fill="#DDD"/></svg>\n')
    write_atomic(out / "listing-concept.html", page.encode("utf-8"))
    write_atomic(out / "listing-concept.svg", svg.encode("utf-8"))
    timestamp = now or _utc_now()
    used = [slot_id for slot_id in dict.fromkeys(slots.values()) if slot_id]
    entries = [{"id": f"listing-v{number:03d}-{kind}", "origin": "listing_concept",
                "path": f"{folder}/listing-concept.{kind}", "sha256": sha256(out / f"listing-concept.{kind}"),
                "parents": used, "registered_at": timestamp, "production_eligible": False, "approved_version": version}
               for kind in ("html", "svg")]
    register_entries(project, entries, timestamp)
    listing = {"id": f"listing-v{number:03d}", "approved_version": version, "slots": slots,
               "files": [entry["id"] for entry in entries]}
    append_event(project, {"type": "listing_built", "listing": listing}, timestamp)
    return {"version": listing["id"], "slots": slots, "missing": [slot for slot in SLOTS if not slots[slot]],
            "files": {"html": entries[0]["path"], "svg": entries[1]["path"], "html_id": entries[0]["id"]}}


def decide_listing(project: Path, payload: dict, now: str | None = None) -> dict:
    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if any(files.get(item, {}).get("origin") != "listing_concept" for item in ids):
        raise ValidationError("Decide on registered listing concepts only.", field="ids",
                              recovery="Use ids returned by `create_listing` build.")
    return record_decision(project, "listing", ids, payload.get("decision"), payload.get("user_quote"), now)
```

The `garment` keep kind is used when the user keeps a cut-out. Add `decide_garments` to `extract.py` in this task, with this test appended to `tests/test_extract.py`:

```python
    def test_garment_keep_decision(self):
        from scripts.studio_core.extract import decide_garments
        with self.assertRaises(ValidationError):
            decide_garments(self.project, {"ids": ["nope"], "decision": "keep", "user_quote": "Yes"}, FIXED_NOW)
```

```python
def decide_garments(project: Path, payload: dict, now: str | None = None) -> dict:
    from .presentation import record_decision

    files = file_index(load_state(project))
    ids = payload.get("ids") or []
    if not ids or any(files.get(item, {}).get("origin") != "extracted_garment" for item in ids):
        raise ValidationError("Decide on registered cut-outs only.", field="ids",
                              recovery="Use ids returned by `extract` register.")
    return record_decision(project, "garment", ids, payload.get("decision"), payload.get("user_quote"), now)
```

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_listing tests.test_extract
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio_core/listing.py scripts/studio_core/extract.py tests/test_listing.py tests/test_extract.py
git commit -m "feat: build Taobao-style listing concepts from kept, eligible images"
```

---

### Task 7: CLI commands and schema

**Files:**
- Modify: `scripts/studio.py`, `schemas/command-io.schema.json`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: every public function from Tasks 3–6.
- Produces the CLI commands `extract`, `create_models`, `try_on`, and `create_listing`, each dispatching on `mode`.

- [ ] **Step 1: Write the failing tests**

Append to `CliTests` in `tests/test_cli.py`:

```python
    def test_presentation_commands_are_wired_and_structured(self):
        project = ready_project(self.root / "p")
        completed, response = self.run_cli("create_models", {"project_dir": str(project), "mode": "install_defaults"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(response["data"]["installed"]), 4)
        for command in ("extract", "create_models", "try_on", "create_listing"):
            completed, response = self.run_cli(command, {"project_dir": str(project), "mode": "bogus"})
            self.assertEqual(completed.returncode, 2, command)
            self.assertEqual(response["command"], command)
            self.assertEqual(response["error"]["field"], "mode")
        completed, response = self.run_cli("create_listing", {"project_dir": str(project), "mode": "build",
                                                              "version": "v001"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("white_background", response["data"]["missing"])
        schema = json.loads((self.bundle / "schemas/command-io.schema.json").read_text("utf-8"))
        names = schema["properties"]["command"]["enum"]
        for command in ("extract", "create_models", "try_on", "create_listing"):
            self.assertIn(command, names)
```

- [ ] **Step 2: Run the test and confirm it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_cli -k presentation
```

Expected: FAIL. The unknown command gives exit 2, `"command": "command_error"`.

- [ ] **Step 3: Implement**

In `scripts/studio.py`, add the imports:

```python
from studio_core.extract import (
    confirm_inventory, decide_garments, plan_extraction, record_consent, record_inventory, register_extraction,
)
from studio_core.listing import build_listing, decide_listing
from studio_core.models import install_defaults, keep_models, plan_models, plan_reference, register_models
from studio_core.tryon import decide_tryon, plan_tryon, register_tryon
```

Add the dispatcher and the four commands above `COMMANDS`:

```python
def _dispatch(payload: dict, modes: dict, command: str) -> dict:
    project = Path(_required(payload, "project_dir"))
    handler = modes.get(payload.get("mode"))
    if handler is None:
        raise ValidationError(
            f"Mode must be one of: {', '.join(modes)}.",
            field="mode",
            recovery=f"See references/presentation.md for the `{command}` workflow.",
        )
    return handler(project, payload)


def command_extract(payload: dict) -> dict:
    now = payload.get("now")
    return _dispatch(payload, {
        "inventory": lambda p, d: record_inventory(p, d, now),
        "confirm": lambda p, d: confirm_inventory(p, d, now),
        "consent": lambda p, d: record_consent(p, d, now),
        "plan": lambda p, d: plan_extraction(p, d),
        "register": lambda p, d: register_extraction(p, d, now),
        "decide": lambda p, d: decide_garments(p, d, now),
    }, "extract")


def command_create_models(payload: dict) -> dict:
    now = payload.get("now")
    return _dispatch(payload, {
        "install_defaults": lambda p, d: install_defaults(p, BUNDLE_DIR),
        "plan": lambda p, d: plan_models(p, d),
        "plan_reference": lambda p, d: plan_reference(p, d),
        "register": lambda p, d: {"entries": register_models(p, d, now)},
        "keep": lambda p, d: keep_models(p, d, now),
    }, "create_models")


def command_try_on(payload: dict) -> dict:
    now = payload.get("now")
    return _dispatch(payload, {
        "plan": lambda p, d: plan_tryon(p, d, now),
        "register": lambda p, d: {"entries": register_tryon(p, d, now)},
        "decide": lambda p, d: decide_tryon(p, d, now),
    }, "try_on")


def command_create_listing(payload: dict) -> dict:
    now = payload.get("now")
    return _dispatch(payload, {
        "build": lambda p, d: build_listing(p, d, now),
        "decide": lambda p, d: decide_listing(p, d, now),
    }, "create_listing")
```

Add these entries to `COMMANDS`:

```python
    "extract": command_extract,
    "create_models": command_create_models,
    "try_on": command_try_on,
    "create_listing": command_create_listing,
```

In `schemas/command-io.schema.json`, add `"extract"`, `"create_models"`, `"try_on"`, and `"create_listing"` to `properties.command.enum`.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add scripts/studio.py schemas/command-io.schema.json tests/test_cli.py
git commit -m "feat: expose extract, create_models, try_on, and create_listing commands"
```

---

### Task 8: Router, docs, trigger description, and evals

**Files:**
- Create: `references/presentation.md`, `evals/scenarios/presentation-listing.json`, `evals/scenarios/near-miss-shopper-tryon.json`, `evals/scenarios/near-miss-mug-background.json`, `evals/scenarios/near-miss-shopee-price.json`. Create each eval file both under `skill/clothing-shop-studio/evals/scenarios/` and under the repo's `evals/scenarios/`.
- Modify: `SKILL.md`, `references/safety-scope.md`, `README.md`, `agents/openai.yaml`
- Test: `tests/test_structure.py`

- [ ] **Step 1: Write the failing structure tests**

Replace `test_description_is_trigger_only` in `tests/test_structure.py` with:

```python
    def test_description_is_trigger_only_and_scoped_to_own_designs(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        description = next(line for line in text.splitlines() if line.startswith("description: "))
        self.assertTrue(description.startswith("description: Use when designing the user's own garments"))
        for phrase in ("catalogue cut-outs", "AI-model try-ons", "listing-concept visuals"):
            self.assertIn(phrase, description)
        self.assertLess(len(description), 420)
        self.assertLess(len(text.splitlines()), 45)

    def test_presentation_reference_and_near_miss_evals_exist(self):
        reference = (ROOT / "references/presentation.md").read_text(encoding="utf-8")
        for code in ("inventory_unconfirmed", "transmission_consent_missing", "garment_not_listing_eligible",
                     "model_not_kept", "real_person_model_refused", "decision_not_affirmative"):
            self.assertIn(code, reference)
        self.assertIn("no prices", reference.lower())
        for name in ("presentation-listing", "near-miss-shopper-tryon", "near-miss-mug-background",
                     "near-miss-shopee-price"):
            self.assertTrue((ROOT / "evals/scenarios" / f"{name}.json").is_file(), name)
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_structure
```

Expected: FAIL, because the description has not changed yet.

- [ ] **Step 3: Write the docs and evals**

1. Set the `SKILL.md` description to exactly:

   > description: Use when designing the user's own garments, apparel graphics, merch, production specs, or factory handoff files, or when turning those designs into catalogue cut-outs, AI-model try-ons, or listing-concept visuals; load it before asking any design-intake question.

2. Add a core rule after "Stay in scope":

   > - **Presentation is for the user's own designs.** Extract, try-on, and listing concepts only use approved designs or images the user owns; try-on uses fictional AI models only; listing concepts carry no prices, sizes, or unconfirmed claims. Follow `references/presentation.md`.

3. Add a router line:

   > - Catalogue, try-on, listing concept: `references/presentation.md`

4. Change the "Stay in scope" bullet to:

   > Decline pricing, quotes, inventory, orders, storefront administration, shopper try-on of other brands' products, and general photo editing, then offer the next in-scope step.

5. Write `references/presentation.md` with these sections:

   - **When to use.** After approval, or with a reference image the user wants turned into cut-outs.
   - **Consent.** Before `extract` plan on a user reference, ask once: "May I send this photo to the image tool to extract the garment?" Record the reply with `extract` mode `consent` (`file_id`, `user_quote`).
   - **Extract.** Five steps:
     1. `inventory`: fields `source_id`, `items[slug, name, category, details, observed, bbox, graphic_policy, unknowns]`.
     2. Show the list and ask one question.
     3. `confirm`: fields `inventory_id`, `user_quote`.
     4. `plan`.
     5. Render each job with the host image tool, then `register` (`inventory_id`, `round`, `results[slug, path, renderer, prompt, estimated_colours for JPEG]`).

     Then open `presentation/extracted/catalogue.html`, show the grid, add the seller notice, and ask one question. Use `decide` for keep, regenerate, or drop.
   - **AI models.**
     - `install_defaults` on first use.
     - `plan_reference` then `register` (`kind: reference`) for any default with a missing image.
     - Custom candidates: `plan` with `range`, render the four jobs, `register` (`kind: candidates`, `round`, `identities`, `results`), show the contact sheet, then `keep` with the user's quote.
     - Never describe or use a real person, celebrity, influencer, or a lookalike.
   - **Try-on.** `plan` with `design_id` or `garment_ids`, `model_id`, and `poses`.
     - Send every `inputs` image to the image tool with the prompt.
     - If the tool cannot take reference images, tell the user identity is held by description only and may drift.
     - `register`, then show each try-on beside its garment and name any visible mismatch. Add the seller notice, ask one question, then `decide`.
   - **Listing concept.** `build` with `version`.
     - Show `listing-concept.svg`. The HTML is for the browser.
     - For each missing slot, offer the command that fills it.
     - It has no prices, sizes, fabric, or other claims. Add the seller notice, ask one question, then `decide`.
   - **Error codes table.** One row for each of the six codes: meaning and recovery.

6. In `references/safety-scope.md`, change the "Out of scope" paragraph to match the new bullet. Add one line under "Privacy and external services":

   > Sending a user's photo to the host image tool for extraction counts as external transmission; `extract` refuses to plan until consent is recorded.

7. In `README.md`:
   - Change "Pricing, inventory, orders, and storefront operations are out of scope." to: "Pricing, inventory, orders, and storefront operations are out of scope; listing concepts are visual mock-ups only."
   - Add a "Presentation" bullet to the feature list naming the four commands.

8. In `agents/openai.yaml`, set:

   ```yaml
   short_description: "Design garments, production handoffs, and listing visuals"
   ```

9. Eval scenario files use the existing format (`id`, `query`, `followups`, `expected`). The files are:

   `presentation-listing.json`:

   ```json
   {
     "id": "presentation-listing",
     "query": "I approved my KIKI KAKA long-sleeve design in my clothing studio project. Put it on one of the default AI models from the front and make a first listing concept for it. No image tool can take reference photos here.",
     "followups": ["Yes, keep that try-on.", "Continue."],
     "expected": [
       "uses the clothing-shop-studio presentation commands",
       "uses only fictional AI models",
       "warns that identity is held by description only",
       "shows no price, size chart, or fabric claim in the listing concept",
       "places the seller notice after each generated visual and before one closing question",
       "asks no more than one question in each response"
     ]
   }
   ```

   `near-miss-shopper-tryon.json`:

   ```json
   {
     "id": "near-miss-shopper-tryon",
     "query": "I'm thinking of buying this Uniqlo jacket online. Can you show me what it would look like on me?",
     "followups": [],
     "expected": [
       "does not start a clothing-shop-studio design intake or presentation flow",
       "does not create a project",
       "explains or redirects without claiming to be a garment-design workflow"
     ]
   }
   ```

   `near-miss-mug-background.json`:

   ```json
   {
     "id": "near-miss-mug-background",
     "query": "Remove the background from this photo of my ceramic mug so I can post it.",
     "followups": [],
     "expected": [
       "does not start a clothing-shop-studio design intake or presentation flow",
       "does not create a project"
     ]
   }
   ```

   `near-miss-shopee-price.json`:

   ```json
   {
     "id": "near-miss-shopee-price",
     "query": "Write a Shopee product description with a price for my new hoodie.",
     "followups": [],
     "expected": [
       "does not quote or invent a price",
       "if the skill is used, declines pricing in one line and offers a listing concept visual instead",
       "asks no more than one question"
     ]
   }
   ```

   Copy all four files into the repo-level `evals/scenarios/` as well.

- [ ] **Step 4: Run the tests and confirm they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Expected: `OK`. Also re-run the existing seller-notice structure test.

- [ ] **Step 5: Commit**

```bash
git add SKILL.md references agents/openai.yaml evals ../../evals/scenarios ../../README.md tests/test_structure.py
git commit -m "docs: route presentation commands and narrow the skill trigger"
```

---

### Task 9: Release verification

**Files:** none are created. Fix anything that fails in the task that owns it.

- [ ] **Step 1: Run the full suites on both Pythons**

From the repo root, run:

```bash
cd skill/clothing-shop-studio && PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
cd skill/clothing-shop-studio && PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tools
```

Expected: `OK` on all four. The first two run on Python 3.14 and 3.9.

- [ ] **Step 2: Run the validator, whitespace check, and hygiene check**

Run:

```bash
PYTHONPATH=<pyyaml site-packages> python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skill/clothing-shop-studio
git diff --check main...HEAD
```

Expected: `Skill is valid!`, and no whitespace errors.

- [ ] **Step 3: Check that a legacy project and the example project are untouched**

Build a project with `git archive 0eaf353` and confirm that the new code:
- `validate`s it clean;
- accepts `extract` mode `inventory` on it;
- and that the example project's `validate --for_export` still reports only `no_current_production_master`.

- [ ] **Step 4: Live headless ordering check**

Run `tools/run_eval.py` on `presentation-listing`, and one near-miss, in a scratch workspace. Confirm:
- the image, then the seller notice, then exactly one `?`;
- the near-miss did not create a project.

- [ ] **Step 5: Clear caches and commit any fixes**

```bash
find . -name __pycache__ -prune -exec rm -rf {} +
git status --short
```

Expected: clean.

Install into `~/.codex/skills` only when the user asks.
