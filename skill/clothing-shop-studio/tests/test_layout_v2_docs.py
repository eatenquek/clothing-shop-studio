"""Layout v2 guidance: asset folders in responses, and docs free of layout v1 advice."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]
REPO = BUNDLE.parents[1]

# Logical folder name -> path relative to the studio root, for project slug "kiki-kaka".
EXPECTED_FOLDERS = {
    "references_user": "references/kiki-kaka/user",
    "references_online": "references/kiki-kaka/online",
    "concepts": "generated/kiki-kaka/concepts",
    "approved": "approved/kiki-kaka",
    "production": "production/kiki-kaka",
    "production_masters": "production/kiki-kaka/masters",
    "extracted": "generated/kiki-kaka/extracted",
    "models": "generated/kiki-kaka/models",
    "tryon": "generated/kiki-kaka/tryon",
    "listings": "exports/kiki-kaka/listings",
}


class AssetFolderResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.studio = (self.home / "Documents/Clothing-Shop-Studio").resolve()
        self.script = BUNDLE / "scripts/studio.py"

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, command: str, payload: dict) -> dict:
        completed = subprocess.run(
            [sys.executable, str(self.script), command],
            input=json.dumps(payload), text=True, capture_output=True, check=False,
            cwd=self.home, env={**os.environ, "HOME": str(self.home)},
        )
        response = json.loads(completed.stdout)
        self.assertTrue(response["ok"], response)
        return response["data"]

    def assert_folders(self, data: dict) -> None:
        self.assertEqual(Path(data["studio_root"]), self.studio)
        # An agent must never derive locations: every folder is absolute and already correct.
        self.assertEqual(
            {key: str(Path(value).relative_to(self.studio)) for key, value in data["asset_folders"].items()},
            EXPECTED_FOLDERS,
        )
        for value in data["asset_folders"].values():
            self.assertTrue(Path(value).is_absolute(), value)
        # Studio-relative forms are what register_file and generate_options payloads take.
        self.assertEqual(data["asset_folders_relative"], EXPECTED_FOLDERS)

    def test_create_project_returns_absolute_asset_folders(self):
        data = self.run_cli("create_project", {"name": "KIKI KAKA"})
        self.assert_folders(data)

    def test_resume_project_returns_absolute_asset_folders(self):
        created = self.run_cli("create_project", {"name": "KIKI KAKA"})
        self.assert_folders(self.run_cli("resume_project", {"project_dir": created["project_dir"]}))

    def test_status_returns_absolute_asset_folders(self):
        created = self.run_cli("create_project", {"name": "KIKI KAKA"})
        self.assert_folders(self.run_cli("status", {"project_dir": created["project_dir"]}))

    def test_returned_reference_folder_is_where_register_file_looks(self):
        created = self.run_cli("create_project", {"name": "KIKI KAKA"})
        folder = Path(created["asset_folders"]["references_user"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "photo.png").write_bytes(b"png-bytes")
        registered = self.run_cli("register_file", {
            "project_dir": created["project_dir"], "origin": "user_reference",
            "path": f"{created['asset_folders_relative']['references_user']}/photo.png",
        })
        self.assertEqual(registered["path"], "references/kiki-kaka/user/photo.png")


SCANNED_DOCS = (
    [BUNDLE / "SKILL.md", REPO / "README.md"]
    + sorted((BUNDLE / "references").rglob("*.md"))
)

# Layout v1 advice that must not survive: choosing a root, and project-relative asset folders.
STALE_V1 = {
    "root selection": re.compile(r"CLOTHING_SHOP_STUDIO_HOME|remember_root|config\.json"),
    "project-local reference folder": re.compile(r"references/(user|online)\b"),
    "project-local concepts folder": re.compile(r"concepts/generated"),
    "project-local approvals folder": re.compile(r"designs/approved"),
    "project-local presentation folder": re.compile(r"presentation/(extracted|models|tryon|listing)"),
    "project-local production folder": re.compile(r"production/(masters|pack-v)"),
    "asset folder under project_dir": re.compile(
        r"(project_dir\S{0,4}|<project>)/(references|concepts|designs|production|presentation)"
    ),
}


class StaleLayoutV1GuidanceTests(unittest.TestCase):
    def test_docs_do_not_describe_layout_v1(self):
        problems = []
        for doc in SCANNED_DOCS:
            for number, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                for label, pattern in STALE_V1.items():
                    if pattern.search(line):
                        problems.append(f"{doc.relative_to(REPO)}:{number} {label}: {line.strip()[:90]}")
        self.assertEqual(problems, [], "stale layout v1 guidance:\n" + "\n".join(problems))

    def test_guard_catches_a_v1_line(self):
        self.assertTrue(STALE_V1["project-local reference folder"].search("copy it into `references/user/`"))
        self.assertFalse(STALE_V1["project-local reference folder"].search("references/<slug>/user/photo.png"))

    def test_skill_and_workflow_teach_asset_folders_and_the_canonical_root(self):
        for doc in (BUNDLE / "SKILL.md", BUNDLE / "references/workflow.md"):
            text = doc.read_text(encoding="utf-8")
            self.assertIn("asset_folders", text, doc.name)
            self.assertIn("Documents/Clothing-Shop-Studio", text, doc.name)


class MigrateLayoutDocsTests(unittest.TestCase):
    def test_skill_md_routes_legacy_projects_to_migrate_layout(self):
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("migrate_layout", text)
        self.assertIn("migration_required", text)
        self.assertIn("user_quote", text)

    def test_workflow_documents_inventory_mapping_and_affirmative_apply(self):
        text = (BUNDLE / "references/workflow.md").read_text(encoding="utf-8")
        for needle in ("migrate_layout", "migration_required", "inventory", "inventory_id",
                       "destination", "user_quote", "affirmative"):
            self.assertIn(needle, text, needle)
        # Apply must never be described as automatic or as accepting a hand-off.
        self.assertRegex(text, r"(?is)only .{0,80}apply|apply .{0,120}only")


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.text = (REPO / "README.md").read_text(encoding="utf-8")

    def test_readme_installs_with_the_installer_not_rsync(self):
        self.assertIn("tools/install_skill.py", self.text)
        self.assertNotIn("rsync", self.text)
        self.assertIn("untracked", self.text)

    def test_readme_explains_canonical_root_and_migration(self):
        self.assertIn("Documents/Clothing-Shop-Studio", self.text)
        self.assertIn("migrate_layout", self.text)

    def test_shared_model_library_uses_the_implemented_folder_name(self):
        presentation = (BUNDLE / "references/presentation.md").read_text(encoding="utf-8")
        for text in (self.text, presentation):
            self.assertIn("generated/_models/", text)
            self.assertNotIn("generated/models/", text)


if __name__ == "__main__":
    unittest.main()
