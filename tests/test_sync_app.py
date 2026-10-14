import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sync_app", ROOT / "tools" / "sync_app.py")
m = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = m
_spec.loader.exec_module(m)

CANONICAL = {"config.yaml", "README.md", "DOCS.md", "CHANGELOG.md", "icon.png", "logo.png",
             "translations/en.yaml", "translations/ko.yaml"}


def make_app(root, slug="mttl_w01", version="26.10.0", image=None, quote='"'):
    """A fake development repository folder `root/slug` with the canonical files and some that are not."""
    app = root / slug
    files = {
        "config.yaml": (f"name: X\nversion: {quote}{version}{quote}\nslug: {slug}\n"
                        f"image: {image or 'ghcr.io/kkqq9320/' + slug}\nports:\n  8080/tcp: 18282\n"),
        "README.md": "r", "DOCS.md": "d", "CHANGELOG.md": "c",
        "icon.png": b"\x89PNG i", "logo.png": b"\x89PNG l",
        "translations/en.yaml": "en", "translations/ko.yaml": "ko",
        "Dockerfile": "FROM x", "run.py": "x", "backend/backend.py": "x",
    }
    for rel, data in files.items():
        path = app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return app


class SyncAppTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_canonical_files_takes_only_the_listed_files(self):
        files = m.canonical_files(make_app(self.tmp))
        self.assertEqual(set(files), CANONICAL)
        self.assertEqual(files["icon.png"], b"\x89PNG i")
        self.assertEqual(files["translations/ko.yaml"], b"ko")

    def test_canonical_files_requires_each_file(self):
        for name in m.REQUIRED:
            with self.subTest(name=name):
                app = make_app(self.tmp / name.replace(".", "_"))
                (app / name).unlink()
                with self.assertRaises(m.SyncError) as cm:
                    m.canonical_files(app)
                self.assertIn(name, str(cm.exception))
        app = make_app(self.tmp / "no_translations")
        shutil.rmtree(app / "translations")
        with self.assertRaises(m.SyncError) as cm:
            m.canonical_files(app)
        self.assertIn("translations", str(cm.exception))

    def test_check_source_rejects_wrong_version_or_image(self):
        files = m.canonical_files(make_app(self.tmp))
        m.check_source("mttl_w01", "26.10.0", files)
        single = m.canonical_files(make_app(self.tmp / "single", quote="'"))
        m.check_source("mttl_w01", "26.10.0", single)
        bad = {
            "version": m.canonical_files(make_app(self.tmp / "v", version="26.10.1")),
            "image": m.canonical_files(make_app(self.tmp / "i", image="ghcr.io/other/mttl_w01")),
            "slug": m.canonical_files(make_app(self.tmp / "s", slug="x")),
        }
        for what, source in bad.items():
            with self.subTest(what=what), self.assertRaises(m.SyncError):
                m.check_source("mttl_w01", "26.10.0", source)
        # The version argument itself must be a calendar version without a leading zero.
        leading_zero = m.canonical_files(make_app(self.tmp / "z", version="26.09.0"))
        with self.assertRaises(m.SyncError):
            m.check_source("mttl_w01", "26.09.0", leading_zero)

    def test_tree_differences_reports_each_kind(self):
        files = m.canonical_files(make_app(self.tmp / "src"))
        target = self.tmp / "target"
        m.write_tree(target, files)
        (target / "translations" / "old.yaml").write_bytes(b"old")
        (target / "DOCS.md").write_bytes(b"edited by hand")
        (target / "logo.png").unlink()
        self.assertEqual(m.tree_differences(target, files),
                         ["changed: DOCS.md", "extra: translations/old.yaml", "missing: logo.png"])

    def test_tree_differences_of_missing_folder(self):
        files = {"config.yaml": b"x"}
        self.assertEqual(m.tree_differences(self.tmp / "none", files), ["missing: config.yaml"])

    def test_write_tree_replaces_folder(self):
        files = m.canonical_files(make_app(self.tmp / "src"))
        target = self.tmp / "target"
        (target / "stale" / "deep").mkdir(parents=True)
        (target / "stale" / "deep" / "file.txt").write_bytes(b"x")
        (target / "DOCS.md").write_bytes(b"old")
        m.write_tree(target, files)
        self.assertEqual(m.tree_differences(target, files), [])
        self.assertFalse((target / "stale").exists())

    def test_load_apps(self):
        path = self.tmp / "apps.json"
        path.write_text(json.dumps({"mttl_w01": {"repository": "kkqq9320/ha-lgu-mttl-w01", "path": "mttl_w01"}}),
                        encoding="utf-8")
        self.assertEqual(m.load_apps(path), {"mttl_w01": m.AppSource("kkqq9320/ha-lgu-mttl-w01", "mttl_w01")})

    def test_load_apps_rejects_bad_entries(self):
        for data in ({"mttl_w01": {"repository": "kkqq9320/ha-lgu-mttl-w01"}},
                     {"../x": {"repository": "a/b", "path": "x"}},
                     {"x": {"repository": "not a repo", "path": "x"}},
                     {"x": {"repository": "a/b", "path": "../x"}}):
            with self.subTest(data=data):
                path = self.tmp / "apps.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(m.SyncError):
                    m.load_apps(path)


if __name__ == "__main__":
    unittest.main()
