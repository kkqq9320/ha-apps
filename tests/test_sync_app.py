import contextlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

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


INDEX = {"mediaType": "application/vnd.oci.image.index.v1+json",
         "manifests": [{"platform": {"os": "linux", "architecture": "amd64"}},
                       {"platform": {"os": "unknown", "architecture": "unknown"}},
                       {"platform": {"os": "linux", "architecture": "arm64"}}]}
TOKEN_URL = "https://ghcr.io/token?scope=repository:kkqq9320/mttl_w01:pull&service=ghcr.io"
MANIFEST_URL = "https://ghcr.io/v2/kkqq9320/mttl_w01/manifests/26.10.0"


class FakeResponse(io.BytesIO):
    status = 200


class FakeOpener:
    """Answers each URL with a fixed (status, body) and records the requests it got."""

    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        status, body = self.routes[request.full_url]
        data = json.dumps(body).encode() if not isinstance(body, bytes) else body
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "error", {}, io.BytesIO(data))
        return FakeResponse(data)


def opener(manifest=(200, INDEX), token=(200, {"token": "t"})):
    return FakeOpener({TOKEN_URL: token, MANIFEST_URL: manifest})


def run_main(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = m.main([str(a) for a in args])
    return rc, out.getvalue(), err.getvalue()


class CheckImageTest(unittest.TestCase):
    def test_check_image_accepts_index_with_both_platforms(self):
        fake = opener()
        m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", fake)
        token, manifest = fake.requests
        self.assertEqual(token.full_url, TOKEN_URL)
        self.assertIn("scope=repository:kkqq9320/mttl_w01:pull", token.full_url)
        self.assertTrue(manifest.full_url.endswith("/v2/kkqq9320/mttl_w01/manifests/26.10.0"))
        self.assertEqual(manifest.get_header("Authorization"), "Bearer t")
        self.assertIn("application/vnd.oci.image.index.v1+json", manifest.get_header("Accept"))
        self.assertIn("application/vnd.docker.distribution.manifest.list.v2+json", manifest.get_header("Accept"))

    def test_check_image_rejects_missing_arm64(self):
        index = {"manifests": [{"platform": {"os": "linux", "architecture": "amd64"}}]}
        with self.assertRaises(m.SyncError) as cm:
            m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", opener(manifest=(200, index)))
        self.assertIn("linux/arm64", str(cm.exception))

    def test_check_image_rejects_single_manifest(self):
        single = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "layers": []}
        with self.assertRaises(m.SyncError):
            m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", opener(manifest=(200, single)))
        with self.assertRaises(m.SyncError):
            m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", opener(manifest=(200, b"not json")))

    def test_check_image_reports_status_when_private(self):
        for kind, fake, status in (("token", opener(token=(401, {})), "401"),
                                   ("token", opener(token=(403, {})), "403"),
                                   ("manifest", opener(manifest=(404, {})), "404")):
            with self.subTest(kind=kind, status=status):
                with self.assertRaises(m.SyncError) as cm:
                    m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", fake)
                self.assertIn(status, str(cm.exception))
                self.assertIn("ghcr.io/kkqq9320/mttl_w01:26.10.0", str(cm.exception))

    def test_check_image_requires_ghcr(self):
        with self.assertRaises(m.SyncError):
            m.check_image("docker.io/kkqq9320/mttl_w01", "26.10.0", opener())

    def test_check_image_guesses_private_only_for_client_errors(self):
        with self.assertRaises(m.SyncError) as cm:
            m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", opener(manifest=(503, {})))
        self.assertIn("503", str(cm.exception))
        self.assertNotIn("private", str(cm.exception))
        with self.assertRaises(m.SyncError) as cm:
            m.check_image("ghcr.io/kkqq9320/mttl_w01", "26.10.0", opener(manifest=(404, {})))
        self.assertIn("private or missing", str(cm.exception))


class ConfigValuesTest(unittest.TestCase):
    def test_config_values_rejects_values_it_cannot_read(self):
        for text in ("name: >-\n  LG U+\n", "name: |\n  X\n", "name: !!str X\n", "name: &a X\n",
                     "name: *a\n", "name: @x\n", "name: %x\n", "name: `x`\n"):
            with self.subTest(text=text), self.assertRaises(m.SyncError) as cm:
                m.config_values(text)
            self.assertIn("name", str(cm.exception))

    def test_config_values_rejects_plain_value_on_two_lines(self):
        with self.assertRaises(m.SyncError) as cm:
            m.config_values('image: ghcr.io/kkqq9320\n  /mttl_w01\nversion: "26.10.0"\n')
        self.assertIn("image", str(cm.exception))

    def test_config_values_reads_tab_comment_and_skips_flow_collections(self):
        values = m.config_values("arch: [amd64, aarch64]\nmap: {a: 1}\nversion: 26.10.0\t# first\n")
        self.assertEqual(values, {"version": "26.10.0"})


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = self.tmp / "ha-apps"
        self.repo.mkdir()
        (self.repo / "apps.json").write_text(
            json.dumps({"mttl_w01": {"repository": "kkqq9320/ha-lgu-mttl-w01", "path": "mttl_w01"}}),
            encoding="utf-8")
        self.src = self.tmp / "dev"
        make_app(self.src)

    def update(self, version="26.10.0"):
        return run_main("--repo", self.repo, "update", "mttl_w01", version, "--source", self.src, "--skip-image")

    def test_update_command_with_local_source(self):
        rc, out, err = self.update()
        self.assertEqual(rc, 0, err)
        self.assertEqual(m.tree_differences(self.repo / "mttl_w01", m.canonical_files(self.src / "mttl_w01")), [])
        self.assertFalse((self.repo / "mttl_w01" / "Dockerfile").exists())

    def test_update_command_rejects_unknown_app(self):
        rc, _, err = run_main("--repo", self.repo, "update", "other", "26.10.0", "--source", self.src, "--skip-image")
        self.assertEqual(rc, 1)
        self.assertIn("other", err)

    def test_update_command_rejects_bad_version(self):
        for version in ("26.09.0", "26.10.1"):
            with self.subTest(version=version):
                rc, _, err = self.update(version)
                self.assertEqual(rc, 1)
                self.assertTrue(err.startswith("error: "), err)
                self.assertFalse((self.repo / "mttl_w01").exists())

    def test_check_command_detects_hand_edit(self):
        self.assertEqual(self.update()[0], 0)
        rc, _, err = run_main("--repo", self.repo, "check", "--app", "mttl_w01", "--source", self.src, "--skip-image")
        self.assertEqual(rc, 0, err)
        (self.repo / "mttl_w01" / "DOCS.md").write_bytes(b"edited by hand")
        rc, _, err = run_main("--repo", self.repo, "check", "--app", "mttl_w01", "--source", self.src, "--skip-image")
        self.assertEqual(rc, 1)
        self.assertIn("changed: DOCS.md", err)

    def test_check_command_rejects_folder_not_in_apps_json(self):
        (self.repo / "other").mkdir()
        (self.repo / "other" / "config.yaml").write_bytes(b"name: other\n")
        rc, _, err = run_main("--repo", self.repo, "check", "--skip-image")
        self.assertEqual(rc, 1)
        self.assertIn("other", err)

    def test_check_command_skips_listed_app_without_folder(self):
        rc, out, err = run_main("--repo", self.repo, "check", "--skip-image")
        self.assertEqual(rc, 0, err)
        self.assertIn("not released yet: mttl_w01", out)

    def test_check_command_source_needs_app(self):
        rc, _, err = run_main("--repo", self.repo, "check", "--source", self.src, "--skip-image")
        self.assertEqual(rc, 1)
        self.assertIn("--app", err)

    def test_check_command_validates_version_before_fetching(self):
        (self.repo / "mttl_w01").mkdir()
        (self.repo / "mttl_w01" / "config.yaml").write_bytes(b"name: X\nslug: mttl_w01\n")
        calls = []

        def fake_fetch(*args):
            calls.append(args)
            raise m.SyncError("fetched")

        with mock.patch.object(m, "fetch_source", fake_fetch):
            rc, _, err = run_main("--repo", self.repo, "check", "--skip-image")
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [])
        self.assertIn("version", err)
        self.assertNotIn("fetched", err)

    def test_list_command(self):
        self.assertEqual(run_main("--repo", self.repo, "list")[1].strip(), "[]")
        self.update()
        self.assertEqual(json.loads(run_main("--repo", self.repo, "list")[1]), ["mttl_w01"])


if __name__ == "__main__":
    unittest.main()
