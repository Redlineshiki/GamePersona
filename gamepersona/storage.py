from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically so an interrupted collection never leaves half a response.
    temp = path.parent / (".writing-" + uuid.uuid4().hex)
    try:
        with temp.open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            f.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class Store:
    def __init__(self, root: Path | str = "artifacts"):
        self.root = Path(root).resolve()

    def path(self, snapshot: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", snapshot):
            raise ValueError("快照标识仅支持字母、数字、下划线和连字符（最多 80 字符）")
        return self.root / "snapshots" / snapshot

    def load(self, snapshot: str, source: str | None = None, ready: bool = True) -> dict:
        manifest = read_json(self.path(snapshot) / "manifest.json")
        if source and manifest["source"] != source:
            raise ValueError(f"快照 {snapshot} 的来源不是 {source}")
        if ready and manifest["state"] != "ready":
            raise ValueError(f"快照 {snapshot} 尚未完成")
        return manifest

    def create(self, snapshot: str, source: str, config: dict) -> tuple[Path, dict]:
        path = self.path(snapshot)
        if path.exists():
            raise ValueError(f"快照 {snapshot} 已存在；刷新数据请使用新标识")
        path.mkdir(parents=True)
        versions = {"gamepersona": __version__}
        for name in ("duckdb", "httpx"):
            versions[name] = importlib.metadata.version(name)
        manifest = {"snapshot_id": snapshot, "source": source, "state": "building",
                    "created_at": utc_now(), "config": config, "runtime_versions": versions}
        write_json(path / "manifest.json", manifest)
        return path, manifest

    def finish(self, path: Path, manifest: dict, **extra: Any) -> None:
        manifest.update(extra)
        manifest["artifact_hashes"] = {
            p.relative_to(path).as_posix(): sha256(p)
            for p in sorted(path.rglob("*")) if p.is_file() and p.name != "manifest.json"
            and "spill" not in p.relative_to(path).parts and not p.name.startswith(".writing-")
        }
        manifest.update(state="ready", completed_at=utc_now())
        write_json(path / "manifest.json", manifest)

    def verify(self, snapshot: str) -> None:
        manifest = self.load(snapshot)
        for name, expected in manifest["artifact_hashes"].items():
            relative = Path(name)
            if relative.is_absolute() or relative.drive or ".." in relative.parts:
                raise ValueError("快照清单含不安全的路径")
            target = self.path(snapshot) / relative
            if not target.is_file() or sha256(target) != expected:
                raise ValueError(f"快照 {snapshot} 的原始或派生产物已变化：{name}")


def load_credentials(env_file: Path | None = None) -> tuple[str, str]:
    values: dict[str, str] = {}
    if env_file is not None:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, sep, value = line.partition("=")
            if sep and name.strip() in {"STEAM_API_KEY", "STEAM_ID"}:
                values[name.strip()] = value.strip().strip("\"'")
    key = os.environ.get("STEAM_API_KEY") or values.get("STEAM_API_KEY", "")
    steam_id = os.environ.get("STEAM_ID") or values.get("STEAM_ID", "")
    if not key or not re.fullmatch(r"\d{17}", steam_id):
        raise ValueError("请在本地配置 STEAM_API_KEY 和 17 位 STEAM_ID；无需发送到聊天中")
    return key, steam_id
