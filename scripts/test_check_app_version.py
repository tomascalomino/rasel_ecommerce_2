import unittest
from unittest.mock import patch

import check_app_version


class PromotionMergeTests(unittest.TestCase):
    def check_commit(
        self,
        *,
        allow,
        parents="base candidate",
        versions=None,
        trees=None,
    ):
        versions = versions or ["1.0.6", "1.0.3", "1.0.6"]
        trees = trees or ["candidate-tree", "candidate-tree"]

        def git_text(*arguments, **_kwargs):
            if arguments[0] == "rev-parse":
                return "abc123"
            if "--format=%s" in arguments:
                return "Merge pull request #4"
            if "--format=%P" in arguments:
                return parents
            raise AssertionError(arguments)

        with (
            patch.object(check_app_version, "git_text", side_effect=git_text),
            patch.object(check_app_version, "version_at", side_effect=versions),
            patch.object(check_app_version, "tree_at", side_effect=trees),
        ):
            return check_app_version.check_commit(
                "merge",
                allow_promotion_merge=allow,
            )

    def test_accepts_github_merge_that_carries_the_candidate_unchanged(self):
        self.assertEqual(self.check_commit(allow=True), [])

    def test_regular_validation_still_rejects_version_reuse(self):
        errors = self.check_commit(allow=False)
        self.assertTrue(any("no es mayor" in error for error in errors))

    def test_rejects_promotion_merge_that_changes_the_candidate_tree(self):
        errors = self.check_commit(
            allow=True,
            trees=["changed-tree", "candidate-tree"],
        )
        self.assertTrue(any("no es mayor" in error for error in errors))

    def test_rejects_promotion_merge_when_the_trees_cannot_be_resolved(self):
        errors = self.check_commit(allow=True, trees=[None, None])
        self.assertTrue(any("no es mayor" in error for error in errors))

    def test_rejects_candidate_version_that_does_not_advance_main(self):
        errors = self.check_commit(
            allow=True,
            versions=["1.0.6", "1.0.6", "1.0.6"],
        )
        self.assertTrue(any("no es mayor" in error for error in errors))

    def test_rejects_non_merge_commit(self):
        errors = self.check_commit(
            allow=True,
            parents="candidate",
            versions=["1.0.6", "1.0.6"],
            trees=[],
        )
        self.assertTrue(any("no es mayor" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
