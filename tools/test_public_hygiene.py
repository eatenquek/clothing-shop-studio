from pathlib import Path
import re
import subprocess
import unittest


class PublicHygieneTests(unittest.TestCase):
    def test_tracked_text_contains_no_personal_machine_paths(self):
        root = Path(__file__).resolve().parents[1]
        prohibited = (
            "/" + "Users/" + "que" + "kee",
            "50" + "szy",
            "private-" + "var-folders",
            "/" + "var/folders/l0/",
            "claude-" + "501",
            "/" + "private/" + "tmp/",
            "/" + "tmp/",
        )
        home_path = re.compile(r"/" + r"(?:Users|home)" + r"/[^/<\s]+/")
        windows_home = re.compile(r"[A-Za-z]:\\" + r"Users\\[^\\\s]+\\")
        offenders = []
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.splitlines()
        for relative in tracked:
            path = root / relative
            if not path.is_file():
                continue
            try:
                text = path.read_text("utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if (
                any(token in text for token in prohibited)
                or home_path.search(text)
                or windows_home.search(text)
            ):
                offenders.append(str(path.relative_to(root)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
