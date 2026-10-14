import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_app", ROOT / "tools" / "sync_app.py")
m = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = m
_spec.loader.exec_module(m)

HA_APPS = "https://github.com/kkqq9320/ha-apps"
MY_LINK = ("https://my.home-assistant.io/redirect/supervisor_add_addon_repository/"
           "?repository_url=https%3A%2F%2Fgithub.com%2Fkkqq9320%2Fha-apps")


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def heading_levels(text):
    return [len(m.group(1)) for m in re.finditer(r"^(#{1,6}) ", text, re.MULTILINE)]


class RepoTest(unittest.TestCase):
    def test_repository_yaml(self):
        lines = read("repository.yaml").splitlines()
        for line in ("name: kkqq9320 Home Assistant Apps", f"url: {HA_APPS}", "maintainer: kkqq9320"):
            with self.subTest(line=line):
                self.assertIn(line, lines)

    def test_apps_json_lists_mttl_w01(self):
        apps = m.load_apps(ROOT / "apps.json")
        self.assertEqual(apps["mttl_w01"], m.AppSource("kkqq9320/ha-lgu-mttl-w01", "mttl_w01"))

    def test_readme_pair(self):
        en, ko = read("README.md"), read("README.ko.md")
        for src, other in ((en, "README.ko.md"), (ko, "README.md")):
            top = [line for line in src.splitlines() if line.strip()][:3]
            self.assertTrue(any(f"]({other})" in line for line in top), other)
        for name, text in (("README.md", en), ("README.ko.md", ko)):
            for s in (HA_APPS, MY_LINK, "https://github.com/kkqq9320/ha-lgu-mttl-w01", "NOTICE.md"):
                with self.subTest(file=name, s=s):
                    self.assertIn(s, text)
        self.assertTrue(heading_levels(en))
        self.assertEqual(heading_levels(en), heading_levels(ko))

    def test_readme_credits_tuo_and_af950833(self):
        # The spec wants both credits visible in this README as well as in the app's own documents.
        for name, s in (("README.md", "투오 of the Naver HA Cafe"), ("README.md", "af950833"),
                        ("README.ko.md", "네이버 HA 카페 투오님"), ("README.ko.md", "af950833")):
            with self.subTest(file=name, s=s):
                # Compare the text a reader sees: link labels without their targets.
                self.assertIn(s, re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", read(name)))

    def test_tuo_is_named_in_hangul(self):
        # 투오님's name is not "Tuo" in English either.
        for name in ("README.md", "README.ko.md"):
            with self.subTest(file=name):
                self.assertNotRegex(read(name), r"\bTuo\b")

    def test_korean_readme_uses_polite_style(self):
        # Korean sentences end in -니다 (습니다체), not the plain -다.
        for number, line in enumerate(read("README.ko.md").splitlines(), 1):
            with self.subTest(line=number):
                self.assertNotRegex(line, r"[가-힣](?<!니)다(?:[.)]|\s*\||\s*$)")

    def test_claude_md_points_to_agents_md(self):
        self.assertEqual(read("CLAUDE.md"), "@AGENTS.md\n")
        self.assertTrue((ROOT / "AGENTS.md").is_file())


if __name__ == "__main__":
    unittest.main()
