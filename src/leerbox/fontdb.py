"""FontManager: built-in font pack, user imports, search and collection management."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import zipfile
import zlib
from collections import OrderedDict
from dataclasses import dataclass, field

from .figlet import FigFont, FontError, decode_font_bytes, glyph_hash_key, parse_font, render_figlet_rows, RenderOptions
from .raster import RasterFont, parse_raster
from .resources import load_resource

MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_ZIP_RATIO = 200


@dataclass
class FontEntry:
    id: str
    name: str
    type: str                  # figlet | toilet | raster
    meta: dict
    builtin: bool = True
    payload: bytes | None = None   # user fonts keep their bytes here
    offset: int = 0
    length: int = 0
    search_blob: str = field(default="", repr=False)

    @property
    def category(self) -> str:
        return self.meta.get("category", "")

    @property
    def tags(self) -> list[str]:
        return self.meta.get("tags", [])

    @property
    def height(self) -> int:
        return int(self.meta.get("height", 0))


def fuzzy_score(query: str, text: str) -> int:
    """Deterministic fuzzy match score (0 = no match). Shared with the JS edition."""
    q = query.lower().strip()
    t = text.lower()
    if not q:
        return 1
    if t == q:
        return 1000
    if t.startswith(q):
        return 800 - min(len(t), 100)
    i = t.find(q)
    if i >= 0:
        return 600 - min(i, 100) - min(len(t), 100) // 4
    # subsequence with bonuses for consecutive matches and word starts
    score = 0
    ti = 0
    streak = 0
    for ch in q:
        found = t.find(ch, ti)
        if found < 0:
            return 0
        if found == ti:
            streak += 1
            score += 10 + streak * 5
        else:
            streak = 0
            score += 4
        if found == 0 or not t[found - 1].isalnum():
            score += 8
        ti = found + 1
    return max(1, min(399, score - (len(t) - len(q)) // 3))


class LRU(OrderedDict):
    def __init__(self, limit: int):
        super().__init__()
        self.limit = limit
        self.lock = threading.Lock()

    def get_or(self, key, factory):
        with self.lock:
            if key in self:
                self.move_to_end(key)
                return self[key]
        val = factory()
        with self.lock:
            self[key] = val
            while len(self) > self.limit:
                self.popitem(last=False)
        return val


class FontManager:
    def __init__(self, user_dir: str | None = None):
        self.entries: dict[str, FontEntry] = {}
        self.order: list[str] = []
        self._pack: bytes = b""
        self._base = 0
        self._parsed = LRU(160)
        self._hashes: dict[str, str] = {}
        self.user_dir = user_dir
        self.load_builtin()
        if user_dir:
            self.load_user_fonts()

    # ------------------------------------------------------------------ load
    def load_builtin(self) -> None:
        raw = zlib.decompress(load_resource("fontpack.bin"))
        if not raw.startswith(b"LBFP1\n"):
            raise FontError("corrupt font pack")
        nl = raw.index(b"\n", 6)
        n = int(raw[6:nl])
        index = json.loads(raw[nl + 1:nl + 1 + n].decode("utf-8"))
        self._pack = raw
        self._base = nl + 1 + n
        for meta in index:
            prefix = {"figlet": "fig", "toilet": "tlf", "raster": "ras"}[meta["type"]]
            fid = f"{prefix}:{meta['name']}"
            e = FontEntry(fid, meta["name"], meta["type"], meta, True, None, meta["offset"], meta["length"])
            e.search_blob = " ".join([meta["name"], meta.get("category", ""), " ".join(meta.get("tags", [])),
                                      meta.get("author") or "", meta.get("source", "")])
            self.entries[fid] = e
            self.order.append(fid)

    def payload(self, e: FontEntry) -> bytes:
        if e.payload is not None:
            return e.payload
        return self._pack[self._base + e.offset:self._base + e.offset + e.length]

    def font(self, fid: str) -> FigFont | RasterFont:
        e = self.entries[fid]

        def make():
            data = self.payload(e)
            if e.type == "raster":
                return parse_raster(json.loads(data.decode("utf-8")), e.name)
            return parse_font(data, e.name)
        return self._parsed.get_or(fid, make)

    # ---------------------------------------------------------------- search
    def search(self, query: str = "", *, category: str = "All", source: str = "All", kind: str = "All",
               min_height: int = 0, max_height: int = 999, ids: list[str] | None = None,
               unicode_only: bool = False, license_clear: bool = False) -> list[str]:
        pool = ids if ids is not None else self.order
        scored = []
        for fid in pool:
            e = self.entries.get(fid)
            if e is None:
                continue
            if category not in ("All", "") and category != e.category and category not in e.tags:
                continue
            if source not in ("All", "") and e.meta.get("source") != source and not (source == "imported" and not e.builtin):
                continue
            if kind not in ("All", "") and e.type != kind and not (kind == "genuine" and e.type in ("figlet", "toilet")):
                continue
            if not min_height <= e.height <= max_height:
                continue
            if unicode_only and "Unicode" not in e.tags:
                continue
            if license_clear and e.meta.get("licenseTier") != "clear":
                continue
            if query:
                s = max(fuzzy_score(query, e.name) * 2, fuzzy_score(query, e.search_blob))
                if s <= 0:
                    continue
            else:
                s = 0
            scored.append((-s, e.name.lower(), fid))
        scored.sort()
        return [fid for _, _, fid in scored]

    def categories(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for e in self.entries.values():
            counts[e.category] = counts.get(e.category, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def sources(self) -> list[str]:
        return sorted({e.meta.get("source", "") for e in self.entries.values()})

    def stats(self) -> dict:
        genuine = sum(1 for e in self.entries.values() if e.type in ("figlet", "toilet") and e.builtin)
        return {"total": len(self.entries), "genuine": genuine,
                "raster": sum(1 for e in self.entries.values() if e.type == "raster"),
                "imported": sum(1 for e in self.entries.values() if not e.builtin)}

    # --------------------------------------------------------------- imports
    def _content_key(self, font: FigFont) -> str:
        return glyph_hash_key(font, ascii_only=True)

    def builtin_hashes(self) -> dict[str, str]:
        if not self._hashes:
            for fid in self.order:
                e = self.entries[fid]
                if e.type in ("figlet", "toilet") and e.builtin:
                    try:
                        self._hashes[self._content_key(self.font(fid))] = fid
                    except FontError:
                        pass
        return self._hashes

    def import_bytes(self, data: bytes, filename: str, persist: bool = True) -> dict:
        """Validate and register a user FLF/TLF font. Returns a status dict."""
        name = re.sub(r"\.(flf|tlf)$", "", os.path.basename(filename), flags=re.I)[:80] or "font"
        name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
        try:
            text, kind = decode_font_bytes(data)
            font = parse_font(text, name)
        except (FontError, ValueError) as exc:
            return {"ok": False, "file": filename, "error": str(exc)}
        key = self._content_key(font)
        dup = self.builtin_hashes().get(key)
        if dup:
            return {"ok": False, "file": filename, "duplicate": dup,
                    "error": f"duplicate of built-in font {self.entries[dup].name}"}
        digest = hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
        fid = f"usr:{digest[:10]}:{name}"
        if fid in self.entries:
            return {"ok": False, "file": filename, "duplicate": fid, "error": "already imported"}
        payload = text.encode("utf-8", "surrogatepass")
        rows = render_figlet_rows(font, "Ab", RenderOptions())
        meta = {"name": name, "type": "figlet" if kind == "flf" else "toilet", "format": kind.upper(),
                "source": "imported", "licenseTier": "user", "license": "Imported by user",
                "author": None, "height": font.height, "category": "Imported",
                "tags": ["Imported", "Unicode" if kind == "tlf" else "ASCII"], "file": os.path.basename(filename),
                "sampleWidth": max((len(r) for r in rows), default=0), "sha256": digest,
                "coverage": {"glyphs": len(font.glyphs)}, "layout": font.full_layout}
        e = FontEntry(fid, name + " [import]", meta["type"], meta, False, payload)
        e.search_blob = f"{name} imported {kind}"
        self.entries[fid] = e
        self.order.append(fid)
        self._hashes[key] = fid
        if persist and self.user_dir:
            os.makedirs(os.path.join(self.user_dir, "fonts"), exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            with open(os.path.join(self.user_dir, "fonts", f"{digest[:10]}_{safe}.{kind}"), "wb") as fh:
                fh.write(payload)
        return {"ok": True, "file": filename, "id": fid}

    def import_zip(self, data: bytes, persist: bool = True) -> list[dict]:
        if len(data) > MAX_ZIP_BYTES:
            return [{"ok": False, "file": "archive", "error": "ZIP archive too large"}]
        results = []
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            return [{"ok": False, "file": "archive", "error": f"invalid ZIP: {exc}"}]
        with zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                return [{"ok": False, "file": "archive", "error": "too many ZIP entries"}]
            total = 0
            for info in infos:
                n = info.filename
                if info.is_dir() or not re.search(r"\.(flf|tlf)$", n, re.I):
                    continue
                # path traversal / absolute paths are ignored entirely: we only use the basename
                if n.startswith(("/", "\\")) or ".." in n.replace("\\", "/").split("/") or re.match(r"^[A-Za-z]:", n):
                    results.append({"ok": False, "file": n, "error": "unsafe path rejected"})
                    continue
                if info.file_size > 6 * 1024 * 1024:
                    results.append({"ok": False, "file": n, "error": "entry too large"})
                    continue
                if info.compress_size and info.file_size / max(1, info.compress_size) > MAX_ZIP_RATIO:
                    results.append({"ok": False, "file": n, "error": "suspicious compression ratio (zip bomb?)"})
                    continue
                total += info.file_size
                if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
                    results.append({"ok": False, "file": n, "error": "archive exceeds total size limit"})
                    break
                with zf.open(info) as fh:
                    blob = fh.read(6 * 1024 * 1024 + 1)
                if len(blob) > 6 * 1024 * 1024:
                    results.append({"ok": False, "file": n, "error": "entry too large"})
                    continue
                results.append(self.import_bytes(blob, os.path.basename(n), persist))
        if not results:
            results.append({"ok": False, "file": "archive", "error": "no .flf/.tlf fonts found in archive"})
        return results

    def load_user_fonts(self) -> None:
        d = os.path.join(self.user_dir or "", "fonts")
        if not os.path.isdir(d):
            return
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith((".flf", ".tlf")):
                try:
                    with open(os.path.join(d, fn), "rb") as fh:
                        data = fh.read(6 * 1024 * 1024 + 1)
                    disp = re.sub(r"^[0-9a-f]{10}_", "", fn)
                    self.import_bytes(data, disp, persist=False)
                except OSError:
                    continue

    def remove_user(self, fid: str) -> bool:
        e = self.entries.get(fid)
        if e is None or e.builtin:
            return False
        del self.entries[fid]
        self.order.remove(fid)
        self._parsed.pop(fid, None)
        self._hashes = {k: v for k, v in self._hashes.items() if v != fid}
        if self.user_dir:
            d = os.path.join(self.user_dir, "fonts")
            prefix = e.meta.get("sha256", "")[:10]
            if os.path.isdir(d):
                for fn in os.listdir(d):
                    if prefix and fn.startswith(prefix + "_"):
                        try:
                            os.remove(os.path.join(d, fn))
                        except OSError:
                            pass
        return True

    def reset_user(self) -> int:
        ids = [fid for fid, e in self.entries.items() if not e.builtin]
        for fid in ids:
            self.remove_user(fid)
        return len(ids)

    def export_collection(self, ids: list[str], path: str) -> int:
        """Write the selected fonts (original FLF/TLF text) plus a manifest into a ZIP."""
        manifest = []
        count = 0
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            used = set()
            for fid in ids:
                e = self.entries.get(fid)
                if e is None or e.type == "raster":
                    continue
                ext = "tlf" if e.type == "toilet" else "flf"
                base = re.sub(r"[^A-Za-z0-9_.-]", "_", e.meta.get("name", e.name))
                fn = f"{base}.{ext}"
                k = 2
                while fn in used:
                    fn = f"{base}_{k}.{ext}"
                    k += 1
                used.add(fn)
                zf.writestr(fn, self.payload(e))
                manifest.append({k2: e.meta.get(k2) for k2 in ("name", "source", "license", "licenseTier", "author", "repo")} | {"file": fn})
                count += 1
            zf.writestr("MANIFEST.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        return count
