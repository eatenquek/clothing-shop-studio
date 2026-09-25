from __future__ import annotations

import json
import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.studio_core.errors import MigrationRequiredError, ValidationError
from scripts.studio_core.migration import apply_migration, inventory_migration
from scripts.studio_core.store import append_event, load_state


class LayoutMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "projects/legacy"
        (self.project / "metadata").mkdir(parents=True)
        source = self.project / "references/user/photo.txt"
        source.parent.mkdir(parents=True)
        source.write_text("owned reference", encoding="utf-8")
        event = {
            "type": "project_created", "name": "Legacy", "slug": "legacy",
            "timestamp": "2026-09-25T00:00:00Z", "previous_hash": "0" * 64,
        }
        from scripts.studio_core.store import _seal, event_hash, replay_state
        event["event_hash"] = event_hash(event, event["previous_hash"])
        entry = {
            "id": "ref-user-001", "origin": "user_reference", "path": "references/user/photo.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "parents": [],
            "registered_at": "2026-09-25T00:00:01Z", "production_eligible": False,
            "rights": "user-owned-or-licensed", "untrusted_text": True,
            "external_transmission_consent": False,
        }
        registered = _seal(
            {"type": "files_registered", "entries": [entry], "timestamp": "2026-09-25T00:00:01Z"},
            event["event_hash"],
        )
        pack_dir = self.project / "production/pack-v001"
        pack_dir.mkdir(parents=True)
        pack_file = pack_dir / "production-spec.md"
        pack_file.write_text("legacy pack", encoding="utf-8")
        manifest = pack_dir / "manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")
        pack = {
            "version": "pack-v001", "path": "production/pack-v001",
            "files": [{"path": "production-spec.md", "sha256": hashlib.sha256(pack_file.read_bytes()).hexdigest()}],
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        }
        exported = _seal(
            {"type": "production_exported", "pack": pack, "timestamp": "2026-09-25T00:00:02Z"},
            registered["event_hash"],
        )
        events = [event, registered, exported]
        state = replay_state(events)
        (self.project / "metadata/decisions.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in events)
        )
        (self.project / "metadata/state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        from scripts.studio_core.views import render_decisions_md, render_manifest, render_project_yaml
        (self.project / "metadata/manifest.json").write_text(render_manifest(state))
        (self.project / "project.yaml").write_text(render_project_yaml(state))
        (self.project / "decisions.md").write_text(render_decisions_md(events))

    def tearDown(self):
        for path in self.root.rglob("*"):
            try:
                os.chmod(path, stat.S_IRWXU)
            except OSError:
                pass
        self.temp.cleanup()

    def test_inventory_is_non_mutating_and_apply_requires_clear_approval(self):
        source = self.project / "references/user/photo.txt"
        plan = inventory_migration(self.project)
        os.chmod(source, stat.S_IRUSR)
        os.chmod(source.parent, stat.S_IRUSR | stat.S_IXUSR)
        self.assertTrue(source.is_file())
        reference = next(item for item in plan["files"] if item["source_project_relative"] == "references/user/photo.txt")
        self.assertEqual(reference["destination"], "references/legacy/user/photo.txt")
        with self.assertRaises(MigrationRequiredError):
            append_event(self.project, {"type": "answer", "field": "fit", "value": "boxy"})
        with self.assertRaises(ValidationError):
            apply_migration(self.project, plan["inventory_id"], "continue")

        result = apply_migration(self.project, plan["inventory_id"], "I approve this migration")
        self.assertTrue(result["migrated"])
        self.assertFalse(source.exists())
        self.assertTrue((self.root / "references/legacy/user/photo.txt").is_file())
        state = load_state(self.project)
        self.assertEqual(state["layout_version"], 2)
        self.assertEqual(state["path_base"], "studio_root")
        self.assertEqual(state["production"]["packs"][0]["path"], "production/legacy/packs/pack-v001")
        self.assertTrue((self.root / "production/legacy/packs/pack-v001/manifest.json").is_file())

    def test_clean_legacy_project_validates_using_legacy_paths(self):
        from scripts.studio_core.validation import validate_project

        report = validate_project(self.project)
        self.assertTrue(report["ok"], report)

    def test_resume_detects_layout_event_when_journal_status_write_was_interrupted(self):
        from scripts.studio_core.store import append_event

        plan = inventory_migration(self.project)
        mapping = {
            item["source_project_relative"]: item["destination"]
            for item in plan["files"]
        }
        mapping["production/pack-v001"] = "production/legacy/packs/pack-v001"
        append_event(self.project, {
            "type": "layout_migrated", "inventory_id": plan["inventory_id"],
            "user_quote": "I approve this migration", "path_mapping": mapping,
        })
        result = apply_migration(self.project, plan["inventory_id"], "I approve this migration")
        self.assertTrue(result["migrated"])


if __name__ == "__main__":
    unittest.main()
