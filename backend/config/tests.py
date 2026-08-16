from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .version import APP_VERSION


class AppVersionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="version-admin",
            email="version@example.com",
            password="test-password",
        )

    def test_settings_version_matches_root_file(self):
        version_file = settings.BASE_DIR.parent / "app_version"
        self.assertEqual(APP_VERSION, version_file.read_text(encoding="utf-8").strip())
        self.assertEqual(settings.APP_VERSION, APP_VERSION)

    def test_admin_displays_current_version(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["app_version"], APP_VERSION)
        self.assertContains(response, f"v{APP_VERSION}")
