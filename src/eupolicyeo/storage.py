import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pyarrow as pa
import pyarrow.parquet as pq

from .settings import artifacts


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(json_bytes(value))
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path):
    return json.loads(path.read_bytes())


def snapshot_dir(snapshot_id: str) -> Path:
    if len(snapshot_id) != 24 or any(c not in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("invalid snapshot ID")
    return artifacts() / "snapshots" / snapshot_id


def write_table(path: Path, records: list) -> None:
    rows = [record.model_dump(mode="json") for record in records]
    # Nested structures are canonical JSON. Scalars remain distinct queryable columns.
    rows = [
        {
            key: json_bytes(value).decode().strip() if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        }
        for row in rows
    ]
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        pq.write_table(pa.Table.from_pylist(rows), temporary, compression="zstd")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
