from pathlib import Path
import base64, gzip, hashlib

root = Path(__file__).resolve().parent
data = base64.b64decode((root / "audit_py.gz.b64").read_text().strip())
source = gzip.decompress(data)
expected = "ddf4f3f2030568e36c6975b371b8ac789438f285bbfaa348523a45884de8ea62"
assert hashlib.sha256(source).hexdigest() == expected
out = root / "run_passive_audit.py"
out.write_bytes(source)
print(out, expected)
