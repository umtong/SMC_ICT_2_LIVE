from pathlib import Path
import base64, gzip, hashlib
root=Path(__file__).resolve().parent
data=base64.b64decode((root/"failed_value_reentry_acceptance_py.gz.b64").read_text().strip())
source=gzip.decompress(data)
expected="0da436771d5351fdd4f3b6b56a52e58d25e499309bcc0b4e41ff01874a0bac6f"
assert hashlib.sha256(source).hexdigest()==expected
out=root/"failed_value_reentry_acceptance.py"
out.write_bytes(source)
print(out, expected)
