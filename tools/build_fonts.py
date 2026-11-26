"""Acquire, validate, de-duplicate and pack the LeerBox font collection.

Inputs : third_party/<repo> clones (see THIRD_PARTY_LICENSES.txt for URLs)
         legacy_v2/LeerBox_Text_Art_Studio_V2.py (raster typography from V2)
         third_party/arabic_fonts/*.ttf (OFL Arabic fonts, rasterized here)
Outputs: src/leerbox/data/fontpack.bin  (zlib-compressed pack shared by both editions)
         FONT_MANIFEST.json            (per-font metadata, source, license status)

Usage: python tools/build_fonts.py [--license-tier clear|all]
  --license-tier clear  only ship fonts whose redistribution terms are explicit
  --license-tier all    (default) also ship community fonts whose license is
                        unstated but which pyfiglet/figlet.js redistribute
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leerbox.figlet import FontError, decode_font_bytes, glyph_hash_key, parse_font, render_figlet  # noqa: E402

TP = ROOT / "third_party"

# Priority order: earlier sources win on duplicates.
SOURCES = [
    {"id": "toilet", "path": TP / "cacalabs_toilet" / "fonts", "repo": "https://github.com/cacalabs/toilet",
     "tier": "clear", "license": "WTFPL-2.0 (TOIlet distribution, see COPYING)"},
    {"id": "pyfiglet-standard", "path": TP / "pwaller_pyfiglet" / "pyfiglet" / "fonts-standard",
     "repo": "https://github.com/pwaller/pyfiglet", "tier": "clear",
     "license": "FIGlet standard distribution (BSD-3-Clause, figlet 2.2.5); listed by pyfiglet as clearly redistributable"},
    {"id": "pyfiglet-contrib", "path": TP / "pwaller_pyfiglet" / "pyfiglet" / "fonts-contrib",
     "repo": "https://github.com/pwaller/pyfiglet", "tier": "unstated",
     "license": "Unstated; redistributed by pyfiglet (MIT project) which considers them public domain"},
    {"id": "figlet.js", "path": TP / "patorjk_figlet.js" / "fonts", "repo": "https://github.com/patorjk/figlet.js",
     "tier": "unstated", "license": "Unstated; redistributed by figlet.js (MIT project)"},
    {"id": "xero", "path": TP / "xero_figlet-fonts", "repo": "https://github.com/xero/figlet-fonts",
     "tier": "unstated", "license": "Unstated; community collection (no repository license)"},
    {"id": "phracker", "path": TP / "phracker_figlet-fonts", "repo": "https://github.com/phracker/figlet-fonts",
     "tier": "unstated", "license": "Unstated; mirror of jave.de FIGlet collection (no repository license)"},
]

LICENSE_PATTERNS = [
    (re.compile(r"public\s+domain", re.I), "Public domain (stated in font header)"),
    (re.compile(r"\bGPL\b|GNU General Public", re.I), "GPL (stated in font header)"),
    (re.compile(r"\bBSD\b", re.I), "BSD (stated in font header)"),
    (re.compile(r"\bMIT\b licen", re.I), "MIT (stated in font header)"),
    (re.compile(r"freely\s+(?:re)?distribut|free(?:ly)?\s+to\s+(?:use|copy|distribute)|may\s+be\s+(?:freely\s+)?(?:copied|distributed)|permission\s+is\s+(?:hereby\s+)?granted", re.I),
     "Free redistribution permitted (stated in font header)"),
    (re.compile(r"creative\s+commons|\bCC0\b|\bCC-BY", re.I), "Creative Commons (stated in font header)"),
]

AUTHOR_PATTERNS = [
    re.compile(r"(?:font\s+)?author\s*[:=]\s*(.+)", re.I),
    re.compile(r"(?:designed|created|drawn|made|converted)\s+by\s*[:]?\s*(.+)", re.I),
    re.compile(r"\bby\s+([A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3})"),
    re.compile(r"copyright\s*(?:\(c\)|©)?\s*(.+)", re.I),
]

NAME_TAGS = [
    (r"3[-_ ]?d|three", "3D"), (r"shadow", "Shadow"), (r"script|cursive|italic|ital", "Script"),
    (r"gothic|fraktur|blackletter|old ?english|bfraktur", "Gothic"), (r"graffiti|tag", "Graffiti"),
    (r"isometric|iso\d", "Isometric"), (r"digital|lcd|led|segment|7seg|clock|digi", "Digital"),
    (r"banner", "Banner"), (r"slant|oblique|lean", "Slanted"), (r"bubble|outline|double|hollow|tube", "Outline"),
    (r"pixel|dot|bit|8x|6x|5x|4x|3x|clb|clr|cli", "Pixel"), (r"block|bloc|blocky|thick|heavy|bold", "Block"),
    (r"mini|small|tiny|thin|short|wee|1row|2row|3x5", "Compact"), (r"big|large|huge|giant|colossal|univers|doh", "Large"),
    (r"braille", "Braille"), (r"cyber|future|tron|matrix|electronic|computer|robot|binary|hex", "Cyberpunk"),
    (r"term|ansi|dos|amiga|c64|retro|amc|crt|vt|ibm|bbs", "Retro terminal"), (r"star ?wars|stellar|space|alien", "Sci-fi"),
    (r"mirror|rev|flip|upside", "Mirrored"), (r"hebrew|ivrit|cyrill|greek|katakana|hiragana|arab|russian|moscow|tengwar|runic|rune|morse|braille", "Non-Latin"),
    (r"horror|blood|ghost|creepy|evil|poison|bloody|danc|halloween", "Horror"), (r"cour|helv|times|sbook|roman|serif|georgia", "Typographic"),
]

BLOCK_CHARS = set("█▀▄▌▐░▒▓■▬▮▯▖▗▘▙▚▛▜▝▞▟")
BOX_CHARS = set("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╭╮╯╰━┃┏┓┗┛┣┫┳┻╋╸╹╺╻")


def detect_license(comment: str) -> str | None:
    for rx, label in LICENSE_PATTERNS:
        if rx.search(comment):
            return label
    return None


def detect_author(comment: str) -> str | None:
    for line in comment.splitlines()[:40]:
        for rx in AUTHOR_PATTERNS:
            m = rx.search(line)
            if m:
                val = re.sub(r"\s+", " ", m.group(1)).strip(" .,:;-*#=@<>")
                val = re.sub(r"\S+@\S+", "", val).strip(" .,<>()")  # drop e-mail addresses
                if 2 <= len(val) <= 60:
                    return val
    return None


def categorize(name: str, font) -> tuple[str, list[str]]:
    tags: list[str] = []
    lname = name.lower()
    for rx, tag in NAME_TAGS:
        if re.search(rx, lname) and tag not in tags:
            tags.append(tag)
    chars = set()
    for cp in range(32, 127):
        for row in font.glyphs.get(cp, []):
            chars.update(row)
    chars.discard(" ")
    chars.discard(font.hardblank)
    if chars & BLOCK_CHARS:
        tags.append("Block")
    if any(0x2800 <= ord(c) <= 0x28FF for c in chars):
        tags.append("Braille")
    if chars & BOX_CHARS:
        tags.append("Box drawing")
    if font.kind == "tlf" or any(ord(c) > 127 for c in chars):
        tags.append("Unicode")
    else:
        tags.append("ASCII")
    if font.height <= 3 and "Compact" not in tags:
        tags.append("Compact")
    if font.height >= 10 and "Large" not in tags:
        tags.append("Large")
    if chars and chars <= set("#@$%&*Mm8O0") and "Block" not in tags:
        tags.append("Filled")
    dedup = []
    for t in tags:
        if t not in dedup:
            dedup.append(t)
    order = ["Braille", "Block", "3D", "Shadow", "Gothic", "Script", "Graffiti", "Isometric", "Digital",
             "Cyberpunk", "Retro terminal", "Outline", "Pixel", "Slanted", "Banner", "Horror", "Sci-fi",
             "Mirrored", "Non-Latin", "Typographic", "Box drawing", "Filled", "Large", "Compact", "Unicode", "ASCII"]
    primary = next((t for t in order if t in dedup), "ASCII")
    return primary, dedup


def coverage(font) -> dict:
    cps = set(font.glyphs)
    def cnt(a, b):
        return sum(1 for c in cps if a <= c <= b)
    letters = sum(1 for c in range(65, 91) if c in cps and any(r.strip() for r in font.glyphs[c]))
    lower = sum(1 for c in range(97, 123) if c in cps and any(r.strip() for r in font.glyphs[c]))
    digits = sum(1 for c in range(48, 58) if c in cps and any(r.strip() for r in font.glyphs[c]))
    return {"glyphs": len(cps), "upper": letters, "lower": lower, "digits": digits,
            "latin1": cnt(0xA0, 0xFF), "latinExt": cnt(0x100, 0x24F), "greek": cnt(0x370, 0x3FF),
            "cyrillic": cnt(0x400, 0x4FF), "hebrew": cnt(0x590, 0x5FF), "other": len([c for c in cps if c > 0x5FF])}


def collect_figlet(tier: str) -> tuple[list[dict], list[dict]]:
    accepted: dict[str, dict] = {}
    ascii_index: dict[str, str] = {}
    rejects: list[dict] = []
    names_used: dict[str, str] = {}
    for src in SOURCES:
        if tier == "clear" and src["tier"] != "clear":
            continue
        if not src["path"].exists():
            print("missing source", src["path"], file=sys.stderr)
            continue
        files = sorted(p for p in src["path"].iterdir() if p.suffix.lower() in (".flf", ".tlf"))
        for p in files:
            raw = p.read_bytes()
            try:
                text, kind = decode_font_bytes(raw)
                font = parse_font(text, p.stem)
            except (FontError, ValueError) as exc:
                rejects.append({"file": f"{src['id']}/{p.name}", "reason": str(exc)})
                continue
            visible = sum(1 for cp in range(33, 127) if cp in font.glyphs and any(r.strip() for r in font.glyphs[cp]))
            if visible < 10:
                rejects.append({"file": f"{src['id']}/{p.name}", "reason": f"only {visible} visible ASCII glyphs"})
                continue
            full_key = glyph_hash_key(font) + f":{font.print_direction}:{font.full_layout}"
            akey = glyph_hash_key(font, ascii_only=True) + f":{font.print_direction}:{font.full_layout}"
            if full_key in accepted:
                accepted[full_key]["aliases"].append(f"{src['id']}/{p.name}")
                continue
            if akey in ascii_index:
                prev = accepted[ascii_index[akey]]
                same_tier = src["tier"] == next(x["tier"] for x in SOURCES if x["id"] == prev["source"])
                if len(font.glyphs) > prev["_glyphs"] and same_tier:
                    # same design, better coverage: replace payload, keep the earlier identity
                    prev["aliases"].append(f"{prev['source']}/{prev['file']} (superseded: fewer glyphs)")
                    new = dict(prev)
                    new.update(_entry(src, p, font, text, kind))
                    new["name"] = prev["name"]
                    new["aliases"] = prev["aliases"]
                    del accepted[ascii_index[akey]]
                    accepted[full_key] = new
                    ascii_index[akey] = full_key
                else:
                    prev["aliases"].append(f"{src['id']}/{p.name} (same ASCII glyphs)")
                continue
            entry = _entry(src, p, font, text, kind)
            base = entry["name"]
            lname = base.lower().replace(" ", "_")
            if lname in names_used:
                entry["name"] = f"{base} ({src['id']})"
            names_used[entry["name"].lower().replace(" ", "_")] = full_key
            entry["aliases"] = []
            accepted[full_key] = entry
            ascii_index[akey] = full_key
    fonts = _merge_near_duplicates(list(accepted.values()))
    fonts = sorted(fonts, key=lambda e: e["name"].lower())
    return fonts, rejects


def _norm_name(n: str) -> str:
    n = re.sub(r"\s*\([^)]*\)$", "", n)
    return re.sub(r"[^a-z0-9]", "", n.lower())


def _merge_near_duplicates(entries: list[dict]) -> list[dict]:
    """Second pass: merge fonts whose visible ASCII glyphs are (nearly) identical.

    * >= 92 of 94 visible glyphs identical  -> same design, regardless of name
    * same normalized name and >= 80 of 94   -> revised version of the same font
    The entry with more glyphs wins (ties: earlier source priority).
    """
    prio = {s["id"]: i for i, s in enumerate(SOURCES)}
    sigs = {}
    for e in entries:
        f = parse_font(e["_text"], e["name"])
        sigs[id(e)] = {c: tuple(r.replace(f.hardblank, " ").rstrip() for r in f.glyphs.get(c, []))
                       for c in range(33, 127)}
    entries.sort(key=lambda e: (e["licenseTier"] != "clear", -e["_glyphs"], prio.get(e["source"], 99)))
    kept: list[dict] = []
    by_height: dict[int, list[dict]] = {}
    for e in entries:
        s = sigs[id(e)]
        dup_of = None
        for k in by_height.get((e["height"], e["direction"]), []):
            ks = sigs[id(k)]
            same = sum(1 for c in s if s[c] == ks.get(c))
            if same >= 92 or (same >= 80 and _norm_name(k["name"]) == _norm_name(e["name"])):
                dup_of = k
                break
        if dup_of is not None:
            dup_of["aliases"].append(f"{e['source']}/{e['file']} (near-duplicate)")
            dup_of["aliases"].extend(e["aliases"])
            # prefer the clean, un-suffixed display name
            if "(" in dup_of["name"] and "(" not in e["name"]:
                dup_of["name"] = e["name"]
            continue
        kept.append(e)
        by_height.setdefault((e["height"], e["direction"]), []).append(e)
    names = {}
    for e in kept:
        key = e["name"].lower()
        if key in names:
            e["name"] = f"{e['name']} ({e['source']})"
        names[e["name"].lower()] = e
    return kept


def _entry(src: dict, p: Path, font, text: str, kind: str) -> dict:
    primary, tags = categorize(p.stem, font)
    header_license = detect_license(font.comment)
    sample = render_figlet(font, "Ab")
    rows = sample.split("\n")
    return {
        "name": p.stem,
        "file": p.name,
        "format": kind.upper(),
        "type": "figlet" if kind == "flf" else "toilet",
        "source": src["id"],
        "repo": src["repo"],
        "licenseTier": "clear" if (src["tier"] == "clear" or header_license) else "unstated",
        "license": header_license or src["license"],
        "author": detect_author(font.comment),
        "height": font.height,
        "baseline": font.baseline,
        "layout": font.full_layout,
        "direction": font.print_direction,
        "hardblank": font.hardblank,
        "sampleWidth": max((len(r) for r in rows), default=0),
        "maxGlyphWidth": font.max_width,
        "category": primary,
        "tags": tags,
        "coverage": coverage(font),
        "sha256": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(),
        "_text": text,
        "_glyphs": len(font.glyphs),
    }


# ---------------------------------------------------------------------------
# Raster typography (bitmap fonts) — V2 legacy set + Arabic fonts
# ---------------------------------------------------------------------------

def _bits_to_hex(rows: list[str]) -> list[str]:
    out = []
    for r in rows:
        r = r.rstrip("0")
        out.append(format(int(r[::-1], 2), "x") if r else "")
    return out


def load_v2_raster() -> tuple[list[dict], list[dict]]:
    """Import the V2 raster designs, dropping exact duplicates and broken weights."""
    src = (ROOT / "legacy_v2" / "LeerBox_Text_Art_Studio_V2.py").read_text(encoding="utf-8")
    m = re.search(r"PACKED='([^']+)'", src)
    data = json.loads(zlib.decompress(base64.b64decode(m.group(1))))
    seen: dict[str, str] = {}
    out, rejects = [], []
    for name, (cat, glyphs) in data["fonts"].items():
        if cat == "Arabic":
            continue  # regenerated from real Arabic TTFs below
        letters = [glyphs.get(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"]
        if any(g is None for g in letters):
            rejects.append({"file": f"v2/{name}", "reason": "missing letters"})
            continue
        # Quality gate: thin/hairline weights rasterize into disconnected strokes at 28px.
        broken = 0
        for g in letters:
            on = sum(r.count("1") for r in g)
            rows_on = sum(1 for r in g if "1" in r)
            if on < rows_on * 1.15:
                broken += 1
        if broken > 8:
            rejects.append({"file": f"v2/{name}", "reason": f"hairline weight: {broken} letters with broken strokes"})
            continue
        key = hashlib.sha256(json.dumps(glyphs, sort_keys=True).encode()).hexdigest()
        if key in seen:
            rejects.append({"file": f"v2/{name}", "reason": f"duplicate of {seen[key]}"})
            continue
        seen[key] = name
        height = len(next(iter(glyphs.values())))
        fam = re.split(r"[-]", name)[0]
        lic = "OFL-1.1" if fam.startswith(("Noto", "Lato")) else ("Bitstream Vera / DejaVu license" if fam.startswith("DejaVu")
                                                                 else "OFL-1.1" if fam.startswith("Liberation") else "OFL-1.1")
        out.append({
            "name": name, "file": None, "format": "RASTER", "type": "raster",
            "source": "v2-raster", "repo": "legacy V2 (rasterized from " + fam + ")",
            "licenseTier": "clear", "license": lic + " (glyphs rasterized from the " + fam + " typeface)",
            "author": None, "height": height, "baseline": height, "layout": 0, "direction": 0,
            "hardblank": "", "sampleWidth": 0, "maxGlyphWidth": max(len(g[0]) for g in glyphs.values()),
            "category": "Raster " + cat, "tags": ["Raster", cat], "coverage": {"glyphs": len(glyphs)},
            "sha256": key,
            "_raster": {"h": height, "base": height, "script": "latin",
                        "g": {c: [len(g[0]), 0] + _bits_to_hex(g) for c, g in glyphs.items()}},
        })
    return out, rejects


def build_arabic_raster() -> list[dict]:
    """Rasterize Arabic presentation forms from bundled OFL TTFs (requires Pillow at build time)."""
    try:
        from arabic_raster import rasterize_arabic_fonts  # tools/arabic_raster.py
    except ImportError:
        sys.path.insert(0, str(Path(__file__).parent))
        from arabic_raster import rasterize_arabic_fonts
    return rasterize_arabic_fonts(TP / "arabic_fonts")


def pack(entries: list[dict]) -> bytes:
    index = []
    blobs = []
    offset = 0
    for e in entries:
        if "_text" in e:
            payload = e["_text"].encode("utf-8", "surrogatepass")
        else:
            payload = json.dumps(e["_raster"], separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        meta = {k: v for k, v in e.items() if not k.startswith("_")}
        meta["offset"] = offset
        meta["length"] = len(payload)
        index.append(meta)
        blobs.append(payload)
        offset += len(payload)
    idx = json.dumps(index, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    raw = b"LBFP1\n" + str(len(idx)).encode() + b"\n" + idx + b"".join(blobs)
    return zlib.compress(raw, 9)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--license-tier", choices=["clear", "all"], default="all")
    ap.add_argument("--no-raster", action="store_true")
    args = ap.parse_args()
    fonts, rejects = collect_figlet(args.license_tier)
    raster, r_rejects = ([], []) if args.no_raster else load_v2_raster()
    arabic = [] if args.no_raster else build_arabic_raster()
    entries = fonts + arabic + raster
    blob = pack(entries)
    out = ROOT / "src" / "leerbox" / "data" / "fontpack.bin"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    genuine = [e for e in entries if e["type"] in ("figlet", "toilet")]
    manifest = {
        "generator": "tools/build_fonts.py",
        "licenseTierBuild": args.license_tier,
        "counts": {
            "genuineFigletToilet": len(genuine),
            "figlet": sum(1 for e in genuine if e["type"] == "figlet"),
            "toilet": sum(1 for e in genuine if e["type"] == "toilet"),
            "clearLicense": sum(1 for e in genuine if e["licenseTier"] == "clear"),
            "unstatedLicense": sum(1 for e in genuine if e["licenseTier"] == "unstated"),
            "arabicRaster": len(arabic),
            "rasterTypography": len(raster),
            "rejected": len(rejects) + len(r_rejects),
            "duplicateAliases": sum(len(e.get("aliases", [])) for e in entries),
        },
        "sources": [{k: str(v) if isinstance(v, Path) else v for k, v in s.items() if k != "path"} for s in SOURCES],
        "fonts": [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries],
        "rejected": rejects + r_rejects,
    }
    (ROOT / "FONT_MANIFEST.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(manifest["counts"], indent=1))
    print(f"fontpack.bin: {len(blob):,} bytes")


if __name__ == "__main__":
    main()
