"""Tests for tests.characterization.require_scanner (the CI guard for the scanner-dependent tests)."""
import os
import unittest
from unittest.mock import patch

from tests import characterization


def decorated(scanner_ok, environment):
    """Build a one-test class under require_scanner with the scanner and CI state as given."""
    with patch.object(characterization, "scanner_available", return_value=scanner_ok), \
            patch.dict(os.environ, environment, clear=False):
        if "CI" not in environment:
            os.environ.pop("CI", None)

        @characterization.require_scanner()
        class Sample(unittest.TestCase):
            def test_body(self):
                self.ran = True

        return Sample("test_body")


class RequireScannerTests(unittest.TestCase):
    def test_decorator_skips_locally_without_scanner(self):
        with self.assertRaises(unittest.SkipTest):
            decorated(False, {}).debug()

    def test_decorator_fails_in_ci_without_scanner(self):
        with self.assertRaises(AssertionError) as caught:
            decorated(False, {"CI": "true"}).debug()
        self.assertIn("required in CI", str(caught.exception))

    def test_decorator_guards_a_plain_test_function(self):
        with patch.object(characterization, "scanner_available", return_value=False), \
                patch.dict(os.environ, {"CI": "true"}, clear=False):
            @characterization.require_scanner()
            def test_body():
                return "ran"

        with self.assertRaises(AssertionError) as caught:
            test_body()
        self.assertIn("required in CI", str(caught.exception))

    def test_decorator_passes_through_with_scanner(self):
        case = decorated(True, {"CI": "true"})
        case.debug()
        self.assertTrue(case.ran)


if __name__ == "__main__":
    unittest.main()
