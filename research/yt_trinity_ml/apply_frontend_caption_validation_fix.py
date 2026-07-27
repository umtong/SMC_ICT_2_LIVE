#!/usr/bin/env python3
"""Require caption syntax, not merely a long HTTP body, in fleet probes."""

from pathlib import Path

TARGET = Path(__file__).with_name("probe_public_frontend_fleet.py")
text = TARGET.read_text(encoding="utf-8")
old = '''        meaningful = " ".join(text.split())\n        return {\n            "status": response.status_code,\n            "bytes": len(raw),\n            "characters": len(meaningful),\n            "content_type": response.headers.get("content-type"),\n            "sha256": hashlib.sha256(raw).hexdigest(),\n            "usable": response.status_code == 200 and len(meaningful) >= 80,\n        }'''
new = '''        meaningful = " ".join(text.split())\n        lowered = text.lower()\n        caption_syntax = (\n            "webvtt" in lowered\n            or "-->" in text\n            or "<text" in lowered\n            or "<tt" in lowered\n            or '"events"' in lowered\n            or '"start_ms"' in lowered\n        )\n        return {\n            "status": response.status_code,\n            "bytes": len(raw),\n            "characters": len(meaningful),\n            "content_type": response.headers.get("content-type"),\n            "sha256": hashlib.sha256(raw).hexdigest(),\n            "caption_syntax": caption_syntax,\n            "usable": response.status_code == 200 and len(meaningful) >= 80 and caption_syntax,\n        }'''
if new in text:
    print("strict caption validation already present")
elif old in text:
    TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("strict caption validation applied")
else:
    raise SystemExit("caption validation anchor missing")
