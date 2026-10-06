import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import run_meta_dispatch as dispatch


class DispatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Path(self.directory.name)
        (self.app / "backend").mkdir()
        (self.app / "backend" / "manage.py").touch()
        self.sha = "a" * 40
        self.database = "postgresql://user:private@staging.example/db?sslmode=require"
        self.env = {
            "GITHUB_REF": "refs/heads/main",
            "META_DISPATCH_SHA": self.sha,
            "DATABASE_URL": self.database,
            "META_DATABASE_FINGERPRINT": dispatch.database_fingerprint(self.database),
            "META_CAPI_ACCESS_TOKEN": "test-only",
        }

    def validate(self, target="production", **changes):
        env = {**self.env, **changes}
        results = [
            subprocess.CompletedProcess([], 0, self.sha + "\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        with patch("run_meta_dispatch.subprocess.run", side_effect=results):
            return dispatch.validate_configuration(target, env, self.app)

    def test_production_accepts_pinned_code_and_correct_tls_database(self):
        self.assertEqual(self.validate(), ("https://rasel.ar", None))

    def test_database_password_rotation_preserves_identity_but_other_database_does_not(
        self,
    ):
        rotated = self.database.replace(":private@", ":rotated@")
        self.assertEqual(
            self.validate(DATABASE_URL=rotated), ("https://rasel.ar", None)
        )
        for database in (
            self.database.replace("staging.example", "wrong.example"),
            self.database.replace("/db?", "/other?"),
            self.database.replace("?sslmode=require", ""),
            "sqlite:///db.sqlite3",
        ):
            with self.subTest(database=database):
                with self.assertRaises(dispatch.DispatchConfigurationError):
                    self.validate(DATABASE_URL=database)

    def test_production_rejects_other_branch_or_test_settings(self):
        for changes in (
            {"GITHUB_REF": "refs/heads/bundle_work"},
            {"META_TEST_EVENT_CODE": "TEST_ONLY"},
            {"META_DISPATCH_ORDER": "8"},
            {"META_CAPI_ACCESS_TOKEN": ""},
            {"META_DISPATCH_SHA": "main"},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(dispatch.DispatchConfigurationError):
                    self.validate(**changes)

    def test_staging_requires_test_mode_and_one_positive_order(self):
        env = {
            "GITHUB_REF": "refs/heads/bundle_work",
            "META_TEST_EVENT_CODE": "TEST_ONLY",
            "META_DISPATCH_ORDER": "8",
        }
        self.assertEqual(
            self.validate("staging", **env),
            ("https://rasel-mp-staging.onrender.com", 8),
        )
        for changes in (
            {"META_TEST_EVENT_CODE": ""},
            {"META_DISPATCH_ORDER": ""},
            {"META_DISPATCH_ORDER": "-1"},
            {"META_DISPATCH_ORDER": "8;echo secret"},
        ):
            with self.assertRaises(dispatch.DispatchConfigurationError):
                self.validate("staging", **{**env, **changes})

    def test_unapproved_or_wrong_downloaded_commit_stops_dispatch(self):
        for results in (
            [subprocess.CompletedProcess([], 0, "b" * 40, "")],
            [
                subprocess.CompletedProcess([], 0, self.sha, ""),
                subprocess.CompletedProcess([], 1, "", ""),
            ],
        ):
            with patch("run_meta_dispatch.subprocess.run", side_effect=results):
                with self.assertRaises(dispatch.DispatchConfigurationError):
                    dispatch.validate_configuration("production", self.env, self.app)

    def test_push_validation_rejects_a_stale_pinned_candidate(self):
        with self.assertRaises(dispatch.DispatchConfigurationError):
            self.validate(GITHUB_EVENT_NAME="push", GITHUB_SHA="b" * 40)

    def test_disabled_dispatch_does_not_read_credentials_or_connect(self):
        with patch.dict(os.environ, {"META_DISPATCH_ENABLED": "0"}):
            with patch("run_meta_dispatch.validate_configuration") as validate:
                self.assertEqual(dispatch.execute("production", self.app), 0)
                validate.assert_not_called()

    def test_unexpected_errors_do_not_expose_connection_details(self):
        output = StringIO()
        with patch(
            "sys.argv",
            ["dispatch", "--target", "production", "--app-dir", str(self.app)],
        ):
            with patch(
                "run_meta_dispatch.execute",
                side_effect=RuntimeError("private password"),
            ):
                with redirect_stderr(output):
                    self.assertEqual(dispatch.main(), 1)
        self.assertIn("RuntimeError", output.getvalue())
        self.assertNotIn("private password", output.getvalue())


if __name__ == "__main__":
    unittest.main()
