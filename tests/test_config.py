import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app import config


def production_environment(**overrides):
    values = {
        "ENV": "production",
        "WHATSAPP_APP_SECRET": "app-secret",
        "WHATSAPP_TOKEN": "whatsapp-token",
        "PHONE_NUMBER_ID": "phone-id",
        "VERIFY_TOKEN": "verify-token",
        "JOB_RUNNER_TOKEN": "job-token",
        "ADMIN_NUMBERS": "27000000000",
    }
    values.update(overrides)
    return values


class ConfigurationTests(unittest.TestCase):
    def test_production_missing_app_secret_fails(self):
        environment = production_environment(WHATSAPP_APP_SECRET="")

        with self.assertRaisesRegex(RuntimeError, "WHATSAPP_APP_SECRET"):
            config.validate_configuration(environment)

    def test_production_missing_whatsapp_token_fails(self):
        environment = production_environment(WHATSAPP_TOKEN="")

        with self.assertRaisesRegex(RuntimeError, "WHATSAPP_TOKEN"):
            config.validate_configuration(environment)

    def test_production_missing_job_runner_token_fails(self):
        environment = production_environment(JOB_RUNNER_TOKEN="")

        with self.assertRaisesRegex(RuntimeError, "JOB_RUNNER_TOKEN"):
            config.validate_configuration(environment)

    def test_development_and_test_have_explicit_relaxed_configuration(self):
        config.validate_configuration({"ENV": "development"})
        config.validate_configuration({"ENV": "test"})

    def test_missing_or_invalid_environment_fails_validation(self):
        with self.assertRaisesRegex(RuntimeError, "ENV must be explicitly set"):
            config.validate_configuration({})
        with self.assertRaisesRegex(RuntimeError, "ENV must be explicitly set"):
            config.validate_configuration({"ENV": "staging"})

    def test_hosted_non_test_environment_uses_production_secret_requirements(self):
        with self.assertRaisesRegex(RuntimeError, "WHATSAPP_TOKEN"):
            config.validate_configuration({
                "ENV": "development",
                "RAILWAY_ENVIRONMENT": "production-like-host",
                "WHATSAPP_APP_SECRET": "app-secret",
                "PHONE_NUMBER_ID": "phone-id",
                "VERIFY_TOKEN": "verify-token",
                "JOB_RUNNER_TOKEN": "job-token",
                "ADMIN_NUMBERS": "27000000000",
            })

    def test_contact_defaults_are_empty(self):
        self.assertEqual(config.DEFAULT_ADMIN_NUMBERS, ())
        self.assertEqual(config.ADMIN_NUMBERS, frozenset())
        self.assertEqual(config.DEFAULT_ATTENDANCE_REPORT_RECIPIENTS, ())
        self.assertEqual(config.ATTENDANCE_REPORT_RECIPIENTS, ())
