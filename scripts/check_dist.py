import argparse
import gzip
import re
from pathlib import Path

from eupolicyeo.publication import SITE_CAP, validate
from eupolicyeo.storage import file_hash, read_json, write_json

parser = argparse.ArgumentParser()
parser.add_argument("--dist", type=Path, default=Path("web/dist"))
parser.add_argument("--report", type=Path, default=Path("artifacts/release_checks.json"))
args = parser.parse_args()
root = args.dist
required = {"index.html", "active.json", "assets", "releases"}
top = {p.name for p in root.iterdir()}
if not required.issubset(top) or top - required - {".nojekyll", "licenses"}:
    raise SystemExit("Unexpected top-level distribution inventory")
active = read_json(root / "active.json")
if not re.fullmatch(r"[a-f0-9]{24}", active["release_id"]):
    raise SystemExit("Invalid active release ID")
manifest = validate(root / "releases" / active["release_id"])
if (
    file_hash(root / "releases" / manifest["release_id"] / "manifest.json")
    != active["manifest_sha256"]
):
    raise SystemExit("Active manifest checksum mismatch")
if {p.name for p in (root / "releases").iterdir()} != {manifest["release_id"]}:
    raise SystemExit("Distribution must contain exactly one release")
asset_pattern = re.compile(
    r"(?:(?:index|search\.worker|dense|ort-wasm-simd-threaded|bbox-map)-[\w-]+\.(?:css|js|mjs|wasm)|map-(?:land|detail)-[\w-]+\.json)"
)
if any(not p.is_file() or not asset_pattern.fullmatch(p.name) for p in (root / "assets").iterdir()):
    raise SystemExit("Unexpected runtime asset")
if (root / "licenses").exists() and any(
    not p.is_file()
    or p.name
    not in {
        "EUPolicyEO-MIT.txt",
        "ONNX-Runtime-MIT.txt",
        "ONNX-Runtime-Third-Party.txt",
        "Tokenizers-Apache-2.0.txt",
    }
    for p in (root / "licenses").iterdir()
):
    raise SystemExit("Unexpected license asset")
project_license = root / "licenses/EUPolicyEO-MIT.txt"
if not project_license.is_file() or file_hash(project_license) != file_hash(
    Path(__file__).resolve().parents[1] / "LICENSE"
):
    raise SystemExit("Distribution must include the project's MIT license")
files = [p for p in root.rglob("*") if p.is_file()]
size = sum(p.stat().st_size for p in files)
shell = [p for p in files if p == root / "index.html" or p.name.startswith("index-")]
if size > SITE_CAP or sum(p.stat().st_size for p in shell) > 2 * 1024**2:
    raise SystemExit("Distribution exceeds site or initial shell budget")
if any(p.is_symlink() for p in root.rglob("*")):
    raise SystemExit("Distribution contains a symlink")
report = {
    "release_id": manifest["release_id"],
    "site_bytes": size,
    "initial_shell_bytes": sum(p.stat().st_size for p in shell),
    "estimated_gzip_shell_bytes": sum(len(gzip.compress(p.read_bytes())) for p in shell),
    "files": len(files),
}
write_json(args.report, report)
print(report)
