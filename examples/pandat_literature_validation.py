"""Check user-supplied database sources against the digests in a local manifest."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

MANIFEST = Path("sources.json")


def sources(directory, fetch=False):
    """Fetch only explicit small source files; always check pinned byte hashes."""
    definitions = json.loads(MANIFEST.read_text(encoding="utf-8"))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for source in definitions:
        path = directory/source["file"]
        if not path.is_file() and fetch:
            with urllib.request.urlopen(source["url"], timeout=60) as response:
                data = response.read(10_000_001)
            if len(data) > 10_000_000:
                raise ValueError("Unexpected source size")
            if "archive_member" in source:
                if hashlib.sha256(data).hexdigest() != source["archive_sha256"]:
                    raise ValueError("Source archive hash mismatch")
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    info = archive.getinfo(source["archive_member"])
                    if info.file_size > 10_000_000:
                        raise ValueError("Unexpected extracted source size")
                    data = archive.read(info)
            if hashlib.sha256(data).hexdigest() != source["sha256"]:
                raise ValueError(f"Downloaded source hash mismatch: {source['file']}")
            path.write_bytes(data)
        if not path.is_file():
            raise ValueError(f"Missing {path}; supply the source or use --fetch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
            raise ValueError(f"Source hash mismatch: {path}")
    return definitions
