"""앱 폴더를 개발 저장소 릴리스 태그의 정본 파일과 같게 복사하고 비교하며, GHCR 이미지를 확인한다.

    python tools/sync_app.py update mttl_w01 26.10.0
    python tools/sync_app.py check
    python tools/sync_app.py list

정본 파일은 Home Assistant가 앱 폴더에서 읽는 파일이다: `config.yaml`, `README.md`, `DOCS.md`,
`CHANGELOG.md`, `icon.png`, `logo.png`, `translations/*.yaml`. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

VERSION_RE = r"^\d{2}\.([1-9]|1[0-2])\.(0|[1-9]\d*)$"
IMAGE_PREFIX = "ghcr.io/kkqq9320/"
REQUIRED = ("config.yaml", "README.md", "DOCS.md", "CHANGELOG.md", "icon.png", "logo.png")
SLUG_RE = r"^[a-z0-9_]+$"
REPOSITORY_RE = r"^[\w.-]+/[\w.-]+$"
# Block scalars, tags, anchors, aliases and reserved indicators: not readable as one-line text here.
UNREADABLE = ("|", ">", "!", "&", "*", "%", "@", "`")
FLOW = ("[", "{")
PLATFORMS = ("linux/amd64", "linux/arm64")
INDEX_TYPES = "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"
TIMEOUT = 30


class SyncError(Exception):
    pass


@dataclass(frozen=True)
class AppSource:
    repository: str
    path: str


def _relative(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and "\\" not in path and not path.startswith("/") and ".." not in parts


def load_apps(path: Path) -> dict[str, AppSource]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SyncError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise SyncError(f"{path.name} must map app slugs to sources")
    apps = {}
    for slug, entry in data.items():
        if not re.fullmatch(SLUG_RE, slug, re.ASCII):
            raise SyncError(f"{path.name}: bad app slug {slug!r}")
        if not isinstance(entry, dict) or set(entry) != {"repository", "path"}:
            raise SyncError(f"{path.name}: {slug} needs exactly 'repository' and 'path'")
        repository, app_path = entry["repository"], entry["path"]
        if not isinstance(repository, str) or not re.fullmatch(REPOSITORY_RE, repository, re.ASCII):
            raise SyncError(f"{path.name}: {slug} has a bad repository {repository!r}")
        if not isinstance(app_path, str) or not _relative(app_path):
            raise SyncError(f"{path.name}: {slug} has a bad path {app_path!r}")
        apps[slug] = AppSource(repository, app_path)
    return apps


def canonical_files(app_dir: Path) -> dict[str, bytes]:
    files = {}
    for name in REQUIRED:
        path = app_dir / name
        if not path.is_file():
            raise SyncError(f"{app_dir.name}: missing {name}")
        files[name] = path.read_bytes()
    translations = sorted(p for p in (app_dir / "translations").glob("*.yaml") if p.is_file())
    if not translations:
        raise SyncError(f"{app_dir.name}: missing translations/*.yaml")
    for path in translations:
        files[f"translations/{path.name}"] = path.read_bytes()
    return files


def _scalar(key: str, raw: str) -> str:
    raw = raw.strip()
    if raw.startswith(UNREADABLE):
        raise SyncError(f"cannot read config.yaml {key!r} ({raw!r}); write it on one line, plain or quoted")
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        rest = raw[end + 1:] if end > 0 else ""
        if end < 0 or (rest.strip() and not rest.strip().startswith("#")) or (quote == '"' and "\\" in raw[:end]):
            raise SyncError(f"cannot read the quoted value of config.yaml {key!r} ({raw!r})")
        return raw[1:end]
    return re.split(r"\s#", raw, maxsplit=1)[0].strip()


def config_values(text: str) -> dict[str, str]:
    """Top-level one-line `key: value` scalars of config.yaml, unquoted; mappings, lists and flow collections are skipped."""
    values: dict[str, str] = {}
    last_scalar = None
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line[0] in " \t":
            if last_scalar and not line.lstrip().startswith("#"):
                raise SyncError(f"config.yaml {last_scalar!r} continues on the next line; write it on one line")
            continue
        key, sep, raw = line.partition(":")
        if not sep:
            raise SyncError(f"cannot read the config line {line!r}")
        last_scalar = None
        if raw.strip().startswith(FLOW):
            continue
        value = _scalar(key, raw)
        if not value:
            continue  # a mapping or a list follows on the next lines
        if key in values:
            raise SyncError(f"config.yaml sets {key!r} twice")
        values[key] = value
        last_scalar = key
    return values


def check_source(slug: str, version: str, files: dict[str, bytes]) -> None:
    if not re.fullmatch(VERSION_RE, version, re.ASCII):
        raise SyncError(f"{version!r} is not a calendar version <YY>.<M>.<N>")
    try:
        values = config_values(files["config.yaml"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError) as exc:
        raise SyncError(f"{slug}: cannot read config.yaml") from exc
    expected = {"slug": slug, "version": version, "image": IMAGE_PREFIX + slug}
    for key, value in expected.items():
        if values.get(key) != value:
            raise SyncError(f"{slug}: config.yaml {key} is {values.get(key)!r}, expected {value!r}")


def _tree(target: Path) -> dict[str, Path]:
    if not target.is_dir():
        return {}
    return {p.relative_to(target).as_posix(): p for p in target.rglob("*") if p.is_file()}


def tree_differences(target: Path, files: dict[str, bytes]) -> list[str]:
    existing = _tree(target)
    found = [f"missing: {rel}" for rel in files if rel not in existing]
    found += [f"extra: {rel}" for rel in existing if rel not in files]
    found += [f"changed: {rel}" for rel, data in files.items()
              if rel in existing and existing[rel].read_bytes() != data]
    return sorted(found)


def write_tree(target: Path, files: dict[str, bytes]) -> None:
    for rel in files:
        if not _relative(rel):
            raise SyncError(f"refusing to write {rel!r}")
    for rel, path in _tree(target).items():
        if rel not in files:
            path.unlink()
    for path in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True) if target.is_dir() else []:
        if not any(path.iterdir()):
            path.rmdir()
    for rel, data in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _fetch(request: urllib.request.Request, urlopen, what: str, ref: str) -> bytes:
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        exc.close()  # the error is also the response; an open one holds the connection
        guess = "; the image is private or missing" if exc.code in (401, 403, 404) else ""
        raise SyncError(f"{ref}: {what} request failed with HTTP {exc.code}{guess}") from exc
    except urllib.error.URLError as exc:
        raise SyncError(f"{ref}: {what} request failed: {exc.reason}") from exc


def check_image(image: str, version: str, urlopen=urllib.request.urlopen) -> None:
    """Pull the image index anonymously, as Home Assistant does, and require both platforms."""
    ref = f"{image}:{version}"
    m = re.fullmatch(r"ghcr\.io/([a-z0-9._-]+/[a-z0-9._-]+)", image, re.ASCII)
    if not m or not re.fullmatch(r"[\w][\w.-]*", version, re.ASCII):
        raise SyncError(f"{ref}: only ghcr.io/<owner>/<name>:<version> can be checked")
    name = m.group(1)
    token_url = f"https://ghcr.io/token?scope=repository:{name}:pull&service=ghcr.io"
    body = _fetch(urllib.request.Request(token_url), urlopen, "token", ref)
    try:
        token = json.loads(body)["token"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncError(f"{ref}: the token response has no token") from exc
    request = urllib.request.Request(f"https://ghcr.io/v2/{name}/manifests/{version}",
                                     headers={"Authorization": f"Bearer {token}", "Accept": INDEX_TYPES})
    body = _fetch(request, urlopen, "manifest", ref)
    try:
        found = {f"{entry['platform']['os']}/{entry['platform']['architecture']}"
                 for entry in json.loads(body)["manifests"] if "platform" in entry}
    except (ValueError, KeyError, TypeError) as exc:
        raise SyncError(f"{ref}: not a multi-arch image index") from exc
    missing = [platform for platform in PLATFORMS if platform not in found]
    if missing:
        raise SyncError(f"{ref}: the image index has no {', '.join(missing)}")


def fetch_source(repository: str, tag: str, dest: Path) -> Path:
    if not re.fullmatch(REPOSITORY_RE, repository, re.ASCII):
        raise SyncError(f"bad repository {repository!r}")
    result = subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--depth", "1", "--branch", tag,
         f"https://github.com/{repository}.git", str(dest)],
        capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode != 0:
        raise SyncError(f"cannot fetch {repository} {tag}: {result.stderr.strip()}")
    return dest


def _app_folders(repo: Path) -> list[str]:
    return sorted(p.name for p in repo.iterdir() if p.is_dir() and (p / "config.yaml").is_file())


def _source_files(app: AppSource, slug: str, version: str, source: Path | None) -> dict[str, bytes]:
    if source is not None:
        return canonical_files(source / app.path)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        return canonical_files(fetch_source(app.repository, f"v{version}", Path(tmp) / slug) / app.path)


def _update(repo: Path, apps: dict[str, AppSource], args: argparse.Namespace) -> None:
    if args.slug not in apps:
        raise SyncError(f"unknown app {args.slug!r}; add it to apps.json first")
    if not re.fullmatch(VERSION_RE, args.version, re.ASCII):
        raise SyncError(f"{args.version!r} is not a calendar version <YY>.<M>.<N>")
    files = _source_files(apps[args.slug], args.slug, args.version, args.source)
    check_source(args.slug, args.version, files)
    if not args.skip_image:
        check_image(IMAGE_PREFIX + args.slug, args.version)
    write_tree(repo / args.slug, files)
    print(f"updated {args.slug} to {args.version}")


def _check(repo: Path, apps: dict[str, AppSource], args: argparse.Namespace) -> int:
    if args.source is not None and not args.app:
        raise SyncError("--source needs --app")
    if args.app and args.app not in apps:
        raise SyncError(f"unknown app {args.app!r}")
    errors = []
    if not args.app:
        errors += [f"app folder not in apps.json: {name}" for name in _app_folders(repo) if name not in apps]
    for slug in [args.app] if args.app else sorted(apps):
        target = repo / slug
        if not target.exists():
            print(f"not released yet: {slug}")
            continue
        try:
            config = target / "config.yaml"
            if not config.is_file():
                raise SyncError(f"{slug}: missing config.yaml")
            version = config_values(config.read_bytes().decode("utf-8")).get("version", "")
            if not re.fullmatch(VERSION_RE, version, re.ASCII):
                raise SyncError(f"{slug}: config.yaml version {version!r} is not a calendar version <YY>.<M>.<N>")
            files = _source_files(apps[slug], slug, version, args.source)
            check_source(slug, version, files)
            differences = tree_differences(target, files)
            if differences:
                raise SyncError("; ".join(f"{slug}: {line}" for line in differences))
            if not args.skip_image:
                check_image(IMAGE_PREFIX + slug, version)
        except (SyncError, UnicodeDecodeError) as exc:
            errors.append(str(exc))
            continue
        print(f"ok: {slug} {version}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy and check app folders against their app repository releases.")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1],
                        help="this repository's checkout (default: the one holding this script)")
    commands = parser.add_subparsers(dest="command", required=True)
    update = commands.add_parser("update", help="replace an app folder with a release's canonical files")
    update.add_argument("slug")
    update.add_argument("version")
    update.add_argument("--source", type=Path, help="a local checkout of the app repository instead of the tag")
    update.add_argument("--skip-image", action="store_true", help="do not check the image on GHCR")
    check = commands.add_parser("check", help="compare app folders with their releases and images")
    check.add_argument("--app", help="check this app only")
    check.add_argument("--source", type=Path, help="a local checkout of the app repository (needs --app)")
    check.add_argument("--skip-image", action="store_true", help="do not check the images on GHCR")
    commands.add_parser("list", help="print the app folders as a JSON array")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            print(json.dumps(_app_folders(args.repo)))
            return 0
        apps = load_apps(args.repo / "apps.json")
        if args.command == "update":
            _update(args.repo, apps, args)
            return 0
        return _check(args.repo, apps, args)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
