"""Access to bundled binary resources (font pack, Arabic tables, mono font).

In the modular development tree resources are read from ``leerbox/data``.
The single-file distribution (built by tools/build_python.py) registers the
same resources in ``EMBEDDED_RESOURCES`` as base64 strings, so the code path
is identical in both layouts. PyInstaller builds use ``sys._MEIPASS``.
"""
from __future__ import annotations

import base64
import os
import sys
import zlib

EMBEDDED_RESOURCES: dict[str, str] = {}
_CACHE: dict[str, bytes] = {}


def _data_dirs() -> list[str]:
    dirs = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.insert(0, os.path.join(meipass, "leerbox", "data"))
    return dirs


def load_resource(name: str) -> bytes:
    """Return the raw bytes of a bundled resource."""
    if name in _CACHE:
        return _CACHE[name]
    if name in EMBEDDED_RESOURCES:
        data = zlib.decompress(base64.b64decode(EMBEDDED_RESOURCES[name]))
        _CACHE[name] = data
        return data
    for d in _data_dirs():
        path = os.path.join(d, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                data = fh.read()
            _CACHE[name] = data
            return data
    raise FileNotFoundError(f"bundled resource not found: {name}")


def has_resource(name: str) -> bool:
    try:
        load_resource(name)
        return True
    except FileNotFoundError:
        return False
