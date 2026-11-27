import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from eupolicyeo.publication import stage_release, unpack

parser = argparse.ArgumentParser()
inputs = parser.add_mutually_exclusive_group(required=True)
inputs.add_argument("--bundle", type=Path)
inputs.add_argument("--archive", type=Path)
parser.add_argument("--sha256")
parser.add_argument("--git-revision", help="Require the archive to match this checkout commit")
args = parser.parse_args()
if args.archive and not args.sha256:
    parser.error("--archive requires --sha256")
with TemporaryDirectory() as scratch:
    bundle = args.bundle or Path(scratch)
    if args.archive:
        unpack(args.archive, args.sha256, bundle)
    manifest = stage_release(bundle, Path("web/public"), git_revision=args.git_revision)
print(manifest["release_id"])
