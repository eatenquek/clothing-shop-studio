from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.install_skill import copy_bundle, install_verified, tree_hash


class InstallSkillTests(unittest.TestCase):
    def test_copy_excludes_caches_and_install_writes_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            (source / "scripts/__pycache__").mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: test\ndescription: test\n---\n")
            (source / "scripts/main.py").write_text("print('ok')\n")
            (source / "scripts/__pycache__/main.pyc").write_bytes(b"cache")
            stage = root / "work/stage"
            copy_bundle(source, stage)
            self.assertFalse((stage / "scripts/__pycache__").exists())
            self.assertEqual(tree_hash(source), tree_hash(stage))

            target = root / "home/.codex/skills/test"
            result = install_verified(source, target, root / "work", "abc123")
            marker = json.loads((target / "INSTALLED_FROM.json").read_text())
            self.assertEqual(marker["source_commit"], "abc123")
            self.assertEqual(marker["bundle_tree_sha256"], result["bundle_tree_sha256"])
            self.assertEqual(tree_hash(source), tree_hash(target))


if __name__ == "__main__":
    unittest.main()
