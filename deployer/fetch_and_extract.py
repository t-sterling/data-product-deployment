#!/usr/bin/env python3
import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import boto3
import yaml

uri = urlparse(os.environ["ARTIFACT_URI"])
if uri.scheme != "s3" or not uri.netloc or not uri.path.lstrip("/"):
    raise SystemExit("ARTIFACT_URI must be s3://bucket/key")
workspace = Path(os.getenv("WORKSPACE", "/workspace"))
archive = workspace / "data-product.zip"
extracted = workspace / "product"
workspace.mkdir(parents=True, exist_ok=True)
boto3.client("s3").download_file(uri.netloc, uri.path.lstrip("/"), str(archive))
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
if actual != os.environ["ARTIFACT_SHA256"]:
    raise SystemExit(f"checksum mismatch: expected {os.environ['ARTIFACT_SHA256']}, got {actual}")
if extracted.exists():
    shutil.rmtree(extracted)
extracted.mkdir()
with zipfile.ZipFile(archive) as bundle:
    members = bundle.infolist()
    if len(members) > 10000 or sum(m.file_size for m in members) > 1024 * 1024 * 1024:
        raise SystemExit("archive exceeds extraction safety limits")
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive path: {member.filename}")
    bundle.extractall(extracted)
product = yaml.safe_load((extracted / "product.yml").read_text())
normalized = {
    "apiVersion": "platform.example.io/v1alpha1",
    "kind": "DataProduct",
    "metadata": {"name": product["name"], "version": str(product["version"])},
    "spec": {"packageRoot": str(extracted)},
}
(extracted / "data-product.yaml").write_text(yaml.safe_dump(normalized, sort_keys=False))
print(f"verified and extracted {uri.geturl()} to {extracted}")
