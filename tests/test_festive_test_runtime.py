import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.festive_test_runtime import (
    TEST_DATABASE_HOST,
    TEST_ENVIRONMENT_ID,
    TEST_PHONE_ID,
    TEST_WABA_ID,
    allowed_payload,
    install_flow_diagnostics,
    install_test_flow_compatibility,
    valid_unsigned_test_session,
    validate_isolation,
    wrap_app,
)


class TestDeploymentBoundary(unittest.TestCase):
    def test_missing_jwt_requires_isolated_allowlisted_durable_session(self):
        request = {"version": "4.0", "action": "INIT", "flow_token": "festive.test"}
        env = {**self.env, "FESTIVE_UAT_MODE": "true"}
        with (
            patch("app.db.get_cursor"),
            patch(
                "app.services.festive_flow_service.load_session",
                return_value={"member_id": 1, "kind": "HOST"},
            ) as session,
            patch(
                "app.services.festive_service.member",
                return_value={"phone": "27999990001"},
            ) as member,
        ):
            self.assertTrue(valid_unsigned_test_session(request, env))
            for changes in (
                {"ENV": "production"},
                {"FESTIVE_UAT_MODE": "false"},
                {"FESTIVE_UAT_ALLOWLIST": "other"},
            ):
                self.assertFalse(
                    valid_unsigned_test_session(request, {**env, **changes})
                )
            self.assertFalse(
                valid_unsigned_test_session(
                    {**request, "flow_token_signature": None}, env
                )
            )
            member.return_value = {"phone": "other"}
            self.assertFalse(valid_unsigned_test_session(request, env))
            session.side_effect = ValueError("expired or unknown session")
            self.assertFalse(valid_unsigned_test_session(request, env))

    def test_present_invalid_jwt_never_uses_test_exception(self):
        endpoint = SimpleNamespace(verify_token_signature=Mock(return_value=False))
        install_test_flow_compatibility(endpoint, self.env)
        with patch("app.festive_test_runtime.valid_unsigned_test_session") as fallback:
            for value in (None, "", "forged", {}):
                self.assertFalse(
                    endpoint.verify_token_signature(
                        {"flow_token_signature": value}, "secret"
                    )
                )
            fallback.assert_not_called()

    def test_signature_diagnostics_preserve_rejection_and_hide_secrets(self):
        verify = Mock(return_value=False)
        endpoint = SimpleNamespace(verify_token_signature=verify)
        install_flow_diagnostics(endpoint)
        for value, reason in (
            (None, "missing"),
            ("private-jwt", "invalid"),
            ({}, "wrong_type"),
        ):
            request = {"flow_token": "private-session"}
            if value is not None:
                request["flow_token_signature"] = value
            with self.assertLogs("app.festive_test_runtime", level="WARNING") as logs:
                self.assertFalse(
                    endpoint.verify_token_signature(request, "private-secret")
                )
            self.assertIn(reason, logs.output[0])
            self.assertNotIn("private", logs.output[0])
            verify.assert_called_with(request, "private-secret")
        verify.return_value = True
        self.assertTrue(endpoint.verify_token_signature({}, "private-secret"))

    def setUp(self):
        self.env = {
            "ENV": "test",
            "RAILWAY_ENVIRONMENT_ID": TEST_ENVIRONMENT_ID,
            "PHONE_NUMBER_ID": TEST_PHONE_ID,
            "DATABASE_URL": f"postgresql://test:test@{TEST_DATABASE_HOST}/railway",
            "WHATSAPP_APP_SECRET": "test-secret",
            "WHATSAPP_TOKEN": "test-token",
            "VERIFY_TOKEN": "test-verify",
            "JOB_RUNNER_TOKEN": "test-job",
            "FESTIVE_UAT_ALLOWLIST": "27999990001",
            "FESTIVE_FLOW_PRIVATE_KEY_B64": "test-key",
        }
        self.payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": TEST_WABA_ID,
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": TEST_PHONE_ID},
                                "messages": [
                                    {"from": "27999990001", "text": {"body": "RUNS"}}
                                ],
                            }
                        }
                    ],
                }
            ],
        }

    def test_startup_rejects_production_before_database_import(self):
        validate_isolation(self.env)
        for name, value in (
            ("ENV", "production"),
            ("RAILWAY_ENVIRONMENT_ID", "production"),
            ("PHONE_NUMBER_ID", "production"),
            ("DATABASE_URL", "postgresql://user:password@production/railway"),
        ):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_isolation({**self.env, name: value})
        for name in ("WHATSAPP_APP_SECRET", "VERIFY_TOKEN", "JOB_RUNNER_TOKEN"):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                validate_isolation({**self.env, name: ""})

    def test_rejects_mixed_batches_wrong_destination_and_malformed_input(self):
        self.assertTrue(allowed_payload(self.payload, {"27999990001"}))
        for field in ("id", "phone", "sender"):
            p = copy.deepcopy(self.payload)
            value = p["entry"][0]["changes"][0]["value"]
            if field == "id":
                p["entry"][0]["id"] = "production"
            elif field == "phone":
                value["metadata"]["phone_number_id"] = "production"
            else:
                value["messages"].append({"from": "unapproved"})
            self.assertFalse(allowed_payload(p, {"27999990001"}))
        for p in (None, [], {}, {"entry": []}, {"entry": [None]}):
            self.assertFalse(allowed_payload(p, {"27999990001"}))

    def test_verification_and_job_protection_and_body_replay(self):
        inner = FastAPI()
        calls = []

        @inner.post("/webhook")
        async def receive(request: Request):
            calls.append(await request.json())
            return {"received": True}

        @inner.post("/jobs/run")
        def jobs():
            return {"ran": True}

        client = TestClient(wrap_app(inner, self.env))
        query = {
            "hub.mode": "subscribe",
            "hub.verify_token": "test-verify",
            "hub.challenge": "1234",
        }
        self.assertEqual(client.get("/webhook", params=query).text, "1234")
        self.assertEqual(client.get("/webhook").status_code, 403)
        self.assertEqual(client.post("/jobs/run").status_code, 403)
        self.assertEqual(
            client.post("/jobs/run", headers={"x-job-token": "test-job"}).status_code,
            200,
        )
        self.assertEqual(
            client.post("/webhook", json=self.payload).json(), {"received": True}
        )
        self.assertEqual(calls, [self.payload])
        self.assertEqual(
            client.post("/webhook", content="invalid").json()["status"],
            "ignored_test_boundary",
        )
        self.assertEqual(client.post("/webhook", content="x" * 65537).status_code, 413)
        self.assertEqual(len(calls), 1)
