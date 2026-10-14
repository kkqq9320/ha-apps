"""앱 폴더를 개발 저장소 릴리스 태그의 정본 파일과 같게 복사하고 비교한다.

정본 파일은 Home Assistant가 앱 폴더에서 읽는 파일이다: `config.yaml`, `README.md`, `DOCS.md`,
`CHANGELOG.md`, `icon.png`, `logo.png`, `translations/*.yaml`. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

VERSION_RE = r"^\d{2}\.([1-9]|1[0-2])\.(0|[1-9]\d*)$"
IMAGE_PREFIX = "ghcr.io/kkqq9320/"
REQUIRED = ("config.yaml", "README.md", "DOCS.md", "CHANGELOG.md", "icon.png", "logo.png")
SLUG_RE = r"^[a-z0-9_]+$"
REPOSITORY_RE = r"^[\w.-]+/[\w.-]+$"


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


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        rest = raw[end + 1:] if end > 0 else ""
        if end < 0 or (rest.strip() and not rest.strip().startswith("#")) or (quote == '"' and "\\" in raw[:end]):
            raise SyncError(f"cannot read the quoted value {raw!r}")
        return raw[1:end]
    return raw.split(" #", 1)[0].strip()


def config_values(text: str) -> dict[str, str]:
    """Top-level `key: value` lines of config.yaml, unquoted; keys that open a block are skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line[0] in " \t#":
            continue
        key, sep, raw = line.partition(":")
        if not sep:
            raise SyncError(f"cannot read the config line {line!r}")
        value = _scalar(raw)
        if not value:
            continue
        if key in values:
            raise SyncError(f"config.yaml sets {key!r} twice")
        values[key] = value
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
