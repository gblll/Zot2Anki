"""Run the synthetic Anki backend acceptance suite in the project .venv."""
import argparse
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import sync_vocabulary as sync


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anki-packages', type=Path, default=sync.DEFAULT_ANKI_PACKAGES)
    args = parser.parse_args()
    sync.DEFAULT_ANKI_PACKAGES = args.anki_packages
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'tests.test_sync_identity', 'tests.test_sync_packages', 'tests.test_sync_transaction'])
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
