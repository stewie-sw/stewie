import importlib
import unittest


class PackageImportTest(unittest.TestCase):
    def test_package_imports(self):
        module = importlib.import_module("stewie_perception")

        self.assertEqual(module.__name__, "stewie_perception")
