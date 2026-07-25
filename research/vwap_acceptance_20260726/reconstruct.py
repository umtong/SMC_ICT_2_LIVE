from __future__ import annotations
import base64, hashlib, tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'source_bundle.tar.gz.b64'
TAR=ROOT/'source_bundle.tar.gz'
EXPECTED_B64='a4ee4664f3a6d846bd8ebed92cb45ccca6c6f70e49cdf42174d97b323181a1c3'
EXPECTED_TAR='580392349259dce51e9511a60e71ff61a671f7283216c51d564d18b419d259d1'
raw=SRC.read_bytes()
if hashlib.sha256(raw).hexdigest()!=EXPECTED_B64:raise SystemExit('base64 checksum mismatch')
payload=base64.b64decode(raw)
if hashlib.sha256(payload).hexdigest()!=EXPECTED_TAR:raise SystemExit('tar checksum mismatch')
TAR.write_bytes(payload)
with tarfile.open(TAR,'r:gz') as tf:tf.extractall(ROOT,filter='data')
print('reconstructed VWAP screen sources')
