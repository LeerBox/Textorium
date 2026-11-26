"""ProjectManager and SettingsManager: validated JSON persistence."""
from __future__ import annotations

import json
import os
import tempfile
import time

from .effects import DEFAULTS as EFFECT_DEFAULTS
from .textart import TextOptions

PROJECT_FORMAT = "leerbox-text-art-project"
PROJECT_VERSION = 3
MAX_PROJECT_BYTES = 8 * 1024 * 1024
MAX_TEXT = 5000


class ProjectError(ValueError):
    pass


def _scalar(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v != v:
            return 0
        return max(-1e6, min(1e6, v))
    if isinstance(v, str):
        return v[:300]
    return None


def sanitize_effects(effects) -> list[dict]:
    out = []
    if not isinstance(effects, list):
        return out
    for e in effects[:40]:
        if not isinstance(e, dict) or e.get("type") not in EFFECT_DEFAULTS:
            continue
        clean = {"type": e["type"], "enabled": bool(e.get("enabled", True))}
        for k, default in EFFECT_DEFAULTS[e["type"]].items():
            if k not in e:
                clean[k] = default
                continue
            v = e[k]
            if isinstance(default, list):
                clean[k] = [str(x)[:16] for x in v[:16]] if isinstance(v, list) else default
            else:
                sv = _scalar(v)
                clean[k] = sv if sv is not None else default
        out.append(clean)
    return out


def make_project(text: str, font_id: str, font_name: str, options: TextOptions, effects: list,
                 export: dict | None = None, extra: dict | None = None) -> dict:
    return {
        "format": PROJECT_FORMAT, "version": PROJECT_VERSION, "app": "LeerBox Text Art Studio 3.0",
        "savedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "text": text[:MAX_TEXT], "font": {"id": font_id, "name": font_name},
        "options": options.to_dict(), "effects": sanitize_effects(effects),
        "export": {k: _scalar(v) for k, v in (export or {}).items()}, "extra": extra or {},
    }


def parse_project(data: bytes | str) -> dict:
    if isinstance(data, bytes):
        if len(data) > MAX_PROJECT_BYTES:
            raise ProjectError("project file too large")
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise ProjectError("project file is not UTF-8") from None
    try:
        obj = json.loads(data)
    except json.JSONDecodeError as exc:
        raise ProjectError(f"invalid JSON: {exc.msg}") from None
    if not isinstance(obj, dict) or obj.get("format") != PROJECT_FORMAT:
        raise ProjectError("not a LeerBox project file")
    if not isinstance(obj.get("version"), int) or obj["version"] > PROJECT_VERSION:
        raise ProjectError("unsupported project version")
    font = obj.get("font") if isinstance(obj.get("font"), dict) else {}
    return {
        "text": str(obj.get("text", ""))[:MAX_TEXT],
        "font": {"id": str(font.get("id", ""))[:200], "name": str(font.get("name", ""))[:200]},
        "options": TextOptions.from_dict(obj.get("options")),
        "effects": sanitize_effects(obj.get("effects")),
        "export": {k: _scalar(v) for k, v in (obj.get("export") or {}).items() if isinstance(k, str)} if isinstance(obj.get("export"), dict) else {},
        "extra": {k: _scalar(v) for k, v in obj.get("extra", {}).items()} if isinstance(obj.get("extra"), dict) else {},
    }


def atomic_write(path: str, data: bytes) -> None:
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def default_user_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "LeerBox", "TextArtStudio3")


class SettingsManager:
    DEFAULTS = {
        "favorites": [], "recents": [], "presets": {}, "last": {}, "geometry": "", "zoom": 1.0,
        "theme_accent": "#7c8cff", "preview_bg": "#0b0d12", "gallery_text": "",
        "image_presets": {}, "palettes": [], "image_last": {}, "export_presets": {},
    }

    def __init__(self, user_dir: str | None = None):
        self.dir = user_dir or default_user_dir()
        self.path = os.path.join(self.dir, "settings.json")
        self.data = dict(self.DEFAULTS)
        self.error: str | None = None
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "rb") as fh:
                raw = fh.read(4 * 1024 * 1024)
            obj = json.loads(raw.decode("utf-8"))
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in self.DEFAULTS and type(v) is type(self.DEFAULTS[k]):
                        self.data[k] = v
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as exc:
            self.error = f"settings could not be read ({exc}); defaults used"

    def save(self) -> None:
        try:
            atomic_write(self.path, json.dumps(self.data, indent=1, ensure_ascii=False).encode("utf-8"))
        except OSError as exc:
            self.error = f"settings could not be saved: {exc}"

    # convenience -----------------------------------------------------------
    def toggle_favorite(self, fid: str) -> bool:
        fav = self.data["favorites"]
        if fid in fav:
            fav.remove(fid)
            on = False
        else:
            fav.append(fid)
            on = True
        self.save()
        return on

    def touch_recent(self, fid: str, limit: int = 30) -> None:
        r = self.data["recents"]
        if fid in r:
            r.remove(fid)
        r.insert(0, fid)
        del r[limit:]
