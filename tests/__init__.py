import unittest
from pathlib import Path


def load_tests(loader, standard_tests, pattern):
    """Unit suites only: the pytest suites in tests/acceptance are run with `python -m pytest tests/acceptance`."""
    suite = unittest.TestSuite()
    here = Path(__file__).parent
    for f in sorted(here.glob("test_*.py")):
        suite.addTests(loader.loadTestsFromName(f"{__name__}.{f.stem}"))
    return suite
