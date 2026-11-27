import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from eupolicyeo.publication import validate
from eupolicyeo.storage import file_hash

parser = argparse.ArgumentParser()
parser.add_argument("bundle", type=Path)
parser.add_argument("archive", type=Path)
parser.add_argument("--git-revision", help="Require a release exported from this commit")
args = parser.parse_args()
manifest = validate(args.bundle)
if args.git_revision is not None and manifest["git_revision"] != args.git_revision:
    parser.error("Release revision differs from the selected commit. Export from a clean checkout.")
with ZipFile(args.archive, "x") as out:
    for name in sorted([*manifest["assets"], "manifest.json"]):
        entry = ZipInfo(name)
        entry.compress_type = ZIP_DEFLATED
        out.writestr(entry, (args.bundle / name).read_bytes())
print(manifest["release_id"], file_hash(args.archive))
