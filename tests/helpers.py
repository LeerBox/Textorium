"""Shared test helpers (unittest; also runnable with pytest)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
GOLD = ROOT / "tests" / "golden"

from leerbox.fontdb import FontManager  # noqa: E402
from leerbox.textart import RenderingEngine  # noqa: E402


@lru_cache(maxsize=1)
def fm() -> FontManager:
    return FontManager()


@lru_cache(maxsize=1)
def engine() -> RenderingEngine:
    return RenderingEngine(fm())


def golden(name: str) -> dict:
    return json.loads((GOLD / name).read_text(encoding="utf-8"))


def tmpdir() -> str:
    return tempfile.mkdtemp(prefix="leerbox_test_")


MINI_FONT = """flf2a$ 3 2 8 15 1 0 24463
mini test font
$$@
$$@
$$@@
""" + "".join(f" {chr(c)}{chr(c)}@\n|{chr(c)}|@\n --@@\n" for c in range(33, 127))
