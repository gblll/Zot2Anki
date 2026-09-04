"""Test-only backend selection for synthetic CI collections."""
import os
from pathlib import Path

if os.environ.get('ZOT2ANKI_TEST_ANKI_PACKAGES'):
    from scripts import sync_vocabulary
    sync_vocabulary.DEFAULT_ANKI_PACKAGES = Path(os.environ['ZOT2ANKI_TEST_ANKI_PACKAGES'])
