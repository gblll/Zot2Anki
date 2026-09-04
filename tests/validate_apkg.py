"""Inspect physical APKG databases and media without importing or resetting cards."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.sync_packages import validate_package


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('package', type=Path)
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args()
    print(json.dumps(validate_package(args.package, clean=args.clean), indent=2))


if __name__ == '__main__':
    main()
