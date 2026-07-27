from pathlib import Path

_parts = sorted(Path(__file__).with_name("_system_part01.inc").parent.glob("_system_part*.inc"))
if not _parts:
    raise ImportError("SMC/ICT system source fragments are missing")
_source = "".join(part.read_text(encoding="utf-8") for part in _parts)
exec(compile(_source, str(Path(__file__)), "exec"), globals(), globals())
