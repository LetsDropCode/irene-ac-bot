import copy
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.festive_test_runtime import (
    TEST_DATABASE_HOST,
    TEST_ENVIRONMENT_ID,
    TEST_PHONE_ID,
    TEST_WABA_ID,
    allowed_payload,
    validate_isolation,
    wrap_app,
)


class TestDeploymentBoundary(unittest.TestCase):
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
