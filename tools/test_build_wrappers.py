from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tools import build_wrappers
from tools.family_manifest import load_manifest


REPO = Path(__file__).resolve().parents[1]


class WrapperBuildTests(unittest.TestCase):
    def temporary_repo(self, root: Path) -> Path:
        repo = root / "repo"
        (repo / "skill").mkdir(parents=True)
        (repo / "tools").mkdir()
        shutil.copytree(REPO / "skill/clothing-shop-studio", repo / "skill/clothing-shop-studio")
        shutil.copy2(REPO / "tools/wrappers.json", repo / "tools/wrappers.json")
        (repo / "README.md").write_text(
            "# Test\n\n<!-- BEGIN GENERATED CLOTHING COMMANDS -->\nold\n"
            "<!-- END GENERATED CLOTHING COMMANDS -->\n",
            encoding="utf-8",
        )
        return repo

    def test_build_is_deterministic_and_check_reports_drift_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = self.temporary_repo(Path(folder))
            self.assertTrue(build_wrappers.build(repo, check=True))
            self.assertEqual(build_wrappers.build(repo, check=False), [])
            before = (repo / "skill/clothing-new/SKILL.md").read_bytes()
            self.assertEqual(build_wrappers.build(repo, check=True), [])
            self.assertEqual(build_wrappers.build(repo, check=False), [])
            self.assertEqual((repo / "skill/clothing-new/SKILL.md").read_bytes(), before)

            skill = repo / "skill/clothing-new/SKILL.md"
            skill.write_text(skill.read_text("utf-8") + "changed\n", encoding="utf-8")
            drift = build_wrappers.build(repo, check=True)
            self.assertEqual(drift, ["skill/clothing-new/SKILL.md differs"])
            self.assertTrue(skill.read_text("utf-8").endswith("changed\n"))

    def test_check_reports_missing_and_unsupported_wrapper_files(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = self.temporary_repo(Path(folder))
            build_wrappers.build(repo, check=False)
            (repo / "skill/clothing-new/agents/openai.yaml").unlink()
            (repo / "skill/clothing-resume/extra.txt").write_text("extra", encoding="utf-8")
            self.assertEqual(
                build_wrappers.build(repo, check=True),
                [
                    "skill/clothing-new/agents/openai.yaml missing",
                    "skill/clothing-resume/extra.txt unsupported",
                ],
            )

    def test_committed_wrappers_are_explicit_only_and_core_delegating(self):
        manifest = load_manifest(REPO)
        for wrapper in manifest["wrappers"]:
            root = REPO / "skill" / wrapper["name"]
            files = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
            self.assertEqual(files, ["SKILL.md", "agents/openai.yaml"], wrapper["name"])
            skill = (root / "SKILL.md").read_text("utf-8")
            yaml_text = (root / "agents/openai.yaml").read_text("utf-8")
            self.assertIn("../clothing-shop-studio/INSTALLED_FROM.json", skill)
            self.assertIn("allow_implicit_invocation: false", yaml_text)
            self.assertNotRegex(skill, r"https?://")
            if wrapper["visual"]:
                self.assertIn("references/safety-scope.md", skill)

        approve = (REPO / "skill/clothing-approve/SKILL.md").read_text("utf-8")
        extract = (REPO / "skill/clothing-extract/SKILL.md").read_text("utf-8")
        self.assertIn("Invocation text is never the approval statement", approve)
        self.assertIn("External image transmission requires a separate affirmative consent reply", extract)

    def test_readme_generated_table_matches_manifest(self):
        manifest = load_manifest(REPO)
        readme = (REPO / "README.md").read_text("utf-8")
        self.assertIn(build_wrappers.render_readme_table(manifest), readme)


if __name__ == "__main__":
    unittest.main()
