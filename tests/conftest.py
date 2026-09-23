import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SAMPLE = ROOT / "data" / "3.pdf"


@pytest.fixture(scope="session")
def doc():
    if not SAMPLE.exists():
        pytest.skip("data/3.pdf not present (sample files are not committed)")
    from epiextract.parser import PdfPlumberParser
    return PdfPlumberParser().parse(SAMPLE)
