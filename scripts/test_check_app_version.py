import unittest
from unittest.mock import patch

import check_app_version


class PostSquashSyncTests(unittest.TestCase):
    def check_sync(self, trees, versions):
        with (
            patch.object(check_app_version, "tree_at", side_effect=trees),
            patch.object(check_app_version, "version_at", side_effect=versions),
        ):
            return check_app_version.check_sync("before", "after")

    def test_accepts_identical_tree_and_version(self):
        self.assertEqual(
            self.check_sync(["tree-1", "tree-1"], ["1.0.1", "1.0.1"]),
            [],
        )

    def test_rejects_changed_tree(self):
        errors = self.check_sync(["tree-1", "tree-2"], ["1.0.1", "1.0.1"])
        self.assertTrue(any("árboles Git idénticos" in error for error in errors))

    def test_rejects_changed_version(self):
        errors = self.check_sync(["tree-1", "tree-1"], ["1.0.1", "1.0.2"])
        self.assertTrue(any("conservar exactamente" in error for error in errors))

    def test_rejects_missing_commit(self):
        errors = self.check_sync([None, "tree-1"], [None, "1.0.1"])
        self.assertTrue(any("commit anterior" in error for error in errors))

    def test_rejects_invalid_version(self):
        errors = self.check_sync(["tree-1", "tree-1"], ["invalid", "invalid"])
        self.assertTrue(any("major.minor.patch" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
