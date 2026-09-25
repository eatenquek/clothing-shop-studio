from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.studio_core.errors import UnsafePathError, ValidationError
from scripts.studio_core.paths import TOP_LEVEL_DIRS, StudioPaths


class StudioPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.paths = StudioPaths(StudioPaths.default_root(self.home))

    def tearDown(self):
        self.temp.cleanup()

    def test_default_root_and_layout_are_canonical_and_idempotent(self):
        self.assertEqual(self.paths.root, (self.home / "Documents/Clothing-Shop-Studio").resolve())
        self.paths.ensure_layout()
        self.paths.ensure_layout()
        self.assertEqual({item.name for item in self.paths.root.iterdir()}, set(TOP_LEVEL_DIRS))

    def test_project_and_asset_paths_are_scoped_to_one_slug(self):
        self.paths.ensure_layout()
        project = self.paths.projects_dir / "kiki-kaka"
        project.mkdir()
        self.assertEqual(self.paths.require_project(project), project.resolve())
        self.assertEqual(
            self.paths.asset_dir("generated", "kiki-kaka"),
            self.paths.root / "generated/kiki-kaka",
        )
        with self.assertRaises(UnsafePathError):
            self.paths.asset_dir("generated", "../other")
        with self.assertRaises(ValidationError):
            self.paths.require_project(self.paths.projects_dir / "missing")

    def test_relative_conversion_rejects_cross_project_and_work_paths(self):
        self.paths.ensure_layout()
        allowed = self.paths.root / "references/kiki-kaka/user/photo.png"
        allowed.parent.mkdir(parents=True)
        allowed.write_bytes(b"photo")
        self.assertEqual(
            self.paths.to_relative(allowed, category="references", slug="kiki-kaka"),
            "references/kiki-kaka/user/photo.png",
        )
        with self.assertRaises(UnsafePathError):
            self.paths.from_relative("references/other/user/photo.png", category="references", slug="kiki-kaka")
        with self.assertRaises(UnsafePathError):
            self.paths.from_relative(".work/evals/result.json", slug="kiki-kaka")

    def test_symlink_escape_is_rejected(self):
        self.paths.ensure_layout()
        outside = self.home / "outside"
        outside.mkdir()
        link = self.paths.root / "generated/escape"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(UnsafePathError):
            self.paths.asset_dir("generated", "escape")


if __name__ == "__main__":
    unittest.main()
