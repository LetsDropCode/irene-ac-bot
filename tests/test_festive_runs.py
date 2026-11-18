import base64
import hashlib
import hmac
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi.testclient import TestClient

from app import festive_endpoint as endpoint
from app import webhook
from app.flows.festive_flow import handle
from app.main import app
from app.services import festive_config as config
from app.services import festive_service as service
from app.services import festive_transport as transport
from scripts.build_festive_flows import build


class FestiveUnitTests(unittest.TestCase):
    def test_T01_T02_exact_dates_and_weekdays(self):
        from datetime import date

        dates = [date.fromisoformat(d) for d in service.DATES]
        self.assertEqual(len(set(dates)), 14)
        self.assertEqual(
            [d.weekday() for d in dates], [6, 1, 2, 3, 5, 6, 1, 2, 3, 6, 1, 2, 5, 6]
        )
        self.assertEqual(dates[-1].year, 2027)

    def test_T28_off_never_reads_database(self):
        with (
            patch.dict(os.environ, {"FESTIVE_RUNS_ENABLED": "false"}),
            patch("app.flows.festive_flow.get_cursor") as db,
        ):
            self.assertIsNone(handle(None, "test", "HOST", None))
        db.assert_not_called()

    def test_uat_allowlist_defaults_closed(self):
        with patch.dict(
            os.environ,
            {
                "FESTIVE_RUNS_ENABLED": "true",
                "FESTIVE_UAT_ALLOWLIST": "",
                "FESTIVE_UAT_MODE": "true",
            },
        ):
            self.assertFalse(config.enabled("27999990001"))

    def test_capability_negotiation(self):
        with patch.dict(
            os.environ,
            {
                "FESTIVE_FLOWS_READY": "true",
                "FESTIVE_FLOW_PRIVATE_KEY_PATH": "/tmp/test-key",
                "FESTIVE_HOST_FLOW_ID": "host-test",
                "FESTIVE_INTERACTIVE_ENABLED": "true",
            },
        ):
            self.assertTrue(config.capabilities()["flows"])
            self.assertFalse(config.capabilities("no_flow")["flows"])
            self.assertTrue(config.capabilities("no_flow")["native"])
            self.assertFalse(config.capabilities("text")["native"])
            payload = transport.flow_payload("test", "HOST", "festive.fake")
            self.assertEqual(
                payload["interactive"]["action"]["parameters"]["flow_action"],
                "data_exchange",
            )
        with (
            patch.dict(os.environ, {"FESTIVE_FLOWS_READY": "false"}),
            self.assertRaises(ValueError),
        ):
            transport.flow_payload("test", "HOST", "festive.fake")

    def test_interactive_list_limit(self):
        rows = [{"id": str(i), "title": str(i)} for i in range(10)]
        self.assertEqual(
            len(
                transport.list_payload("test", "Runs", rows)["interactive"]["action"][
                    "sections"
                ][0]["rows"]
            ),
            10,
        )
        with self.assertRaises(ValueError):
            transport.list_payload("test", "Runs", rows + [{"id": "11", "title": "11"}])
        with self.assertRaises(ValueError):
            transport.list_payload("test", "Runs", [{"id": "1", "title": "X" * 25}])

    def test_reply_button_limits(self):
        self.assertEqual(
            transport.buttons_payload("test", "Confirm", [("yes", "Yes")])[
                "interactive"
            ]["type"],
            "button",
        )
        for choices in ([(str(i), str(i)) for i in range(4)], [("id", "x" * 21)]):
            with self.assertRaises(ValueError):
                transport.buttons_payload("test", "Confirm", choices)

    def test_location_payload(self):
        d = service.validate_details(
            {
                "latitude": -25.9,
                "longitude": 28.2,
                "meeting_point": "Meeting point",
                "location_description": "Public parking",
            }
        )
        self.assertEqual(
            transport.location_payload("test", d)["location"]["latitude"], -25.9
        )
        with self.assertRaises(service.FestiveError):
            service.validate_details({"latitude": "nan", "longitude": 28})

    def test_invalid_times(self):
        for value in ("25:00", "6:00", "12:60", "6pm", 600):
            with self.subTest(value=value), self.assertRaises(service.FestiveError):
                service.validate_details({"start_time": value})

    def test_invalid_urls(self):
        for value in (
            "javascript:alert(1)",
            "http://example.com",
            "https://localhost",
            "https://127.0.0.1",
            "https://example.com:444",
            "https://user:pass@example.com",
            "https://example.com/a b",
        ):
            with self.subTest(value=value), self.assertRaises(service.FestiveError):
                service.validate_url(value)
        self.assertEqual(
            service.validate_url("https://maps.app.goo.gl/example"),
            "https://maps.app.goo.gl/example",
        )

    def test_incomplete_draft_valid_but_not_submittable(self):
        self.assertEqual(
            service.validate_details({"meeting_point": "Park"})["meeting_point"], "Park"
        )
        with self.assertRaises(service.FestiveError):
            service.validate_details({"meeting_point": "Park"}, complete=True)

    def test_distances_validation(self):
        self.assertEqual(
            service.validate_details({"distances": "5 km, 10km, 5km"})["distances"],
            ["5km", "10km"],
        )
        for value in ("0km", "walk", [1], ",".join(f"{i}km" for i in range(1, 10))):
            with self.assertRaises(service.FestiveError):
                service.validate_details({"distances": value})

    def test_three_flow_assets_versions_routing_and_field_contracts(self):
        root = Path(__file__).resolve().parents[1]
        for kind in ("HOST", "JOIN", "MANAGE"):
            asset = json.loads(
                (root / f"app/flows/assets/festive_{kind.lower()}.json").read_text()
            )
            self.assertEqual(asset, build(kind))
            self.assertEqual(
                (asset["version"], asset["data_api_version"]), ("7.3", "4.0")
            )
            ids = {s["id"] for s in asset["screens"]}
            self.assertEqual(ids, set(asset["routing_model"]))
            for screen in asset["screens"]:
                self.assertIn("revision", screen["data"])
                self.assertLessEqual(len(screen["layout"]["children"]), 50)
                self.assertTrue(set(asset["routing_model"][screen["id"]]) <= ids)
                fields = {c.get("name") for c in screen["layout"]["children"]}
                for k in screen["layout"]["children"][-1]["on-click-action"]["payload"]:
                    if k != "revision":
                        self.assertIn(k, fields)
            self.assertEqual(sum(s["terminal"] for s in asset["screens"]), 1)

    def test_webhook_routes_flow_reply_without_trusting_client_fields(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "test-id",
                                        "from": "test",
                                        "type": "interactive",
                                        "interactive": {
                                            "type": "nfm_reply",
                                            "nfm_reply": {
                                                "response_json": json.dumps(
                                                    {
                                                        "flow_token": "festive.fake",
                                                        "member_id": 999,
                                                        "approved": True,
                                                    }
                                                )
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        _, _, _, button = webhook.extract_whatsapp_message(payload)
        self.assertEqual(
            button, {"id": "festive:completion", "flow_token": "festive.fake"}
        )

    def test_webhook_location_and_template_buttons(self):
        for message, expected in [
            (
                {"type": "location", "location": {"latitude": -26, "longitude": 28}},
                "festive:location",
            ),
            (
                {"type": "button", "button": {"payload": "festive:calendar:0"}},
                "festive:calendar:0",
            ),
        ]:
            payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {"id": "test", "from": "test", **message}
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            with patch.dict(
                os.environ,
                {
                    "FESTIVE_RUNS_ENABLED": "true",
                    "FESTIVE_UAT_ALLOWLIST": "test",
                    "FESTIVE_UAT_MODE": "true",
                },
            ):
                self.assertEqual(
                    webhook.extract_whatsapp_message(payload)[3]["id"], expected
                )

    def test_uat_and_feature_off_block_queued_sends(self):
        for env in (
            {"FESTIVE_RUNS_ENABLED": "false"},
            {
                "FESTIVE_RUNS_ENABLED": "true",
                "FESTIVE_UAT_MODE": "true",
                "FESTIVE_UAT_ALLOWLIST": "test",
            },
        ):
            with (
                patch.dict(os.environ, env),
                patch("app.whatsapp._send_direct") as send,
            ):
                transport.deliver_reply(
                    {"payload": transport.text_payload("test", "Hello")}
                )
                send.assert_not_called()

    def test_provider_failure_surfaces_for_queue(self):
        with (
            patch.dict(
                os.environ,
                {"FESTIVE_RUNS_ENABLED": "true", "FESTIVE_UAT_MODE": "false"},
            ),
            patch("app.whatsapp._send_direct", return_value=False),
            self.assertRaises(RuntimeError),
        ):
            transport.deliver_reply(
                {"payload": transport.text_payload("test", "Hello")}
            )


class FestiveEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.pem = cls.private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

    def envelope(self, request):
        aes, iv = os.urandom(16), os.urandom(16)
        encrypted = self.private.public_key().encrypt(
            aes,
            padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
            ),
        )
        b64 = lambda v: base64.b64encode(v).decode()
        return (
            {
                "encrypted_aes_key": b64(encrypted),
                "initial_vector": b64(iv),
                "encrypted_flow_data": b64(
                    AESGCM(aes).encrypt(iv, json.dumps(request).encode(), None)
                ),
            },
            aes,
            iv,
        )

    def test_encrypted_request_response_roundtrip(self):
        # Platform-independent wire contract; this is NOT a real device test.
        request = {"version": "4.0", "action": "ping"}
        body, aes, iv = self.envelope(request)
        decoded, key, initial = endpoint.decrypt(body, self.pem)
        self.assertEqual(decoded, request)
        response = endpoint.encrypt({"data": {"status": "active"}}, key, initial)
        plain = AESGCM(aes).decrypt(
            bytes(b ^ 255 for b in iv), base64.b64decode(response), None
        )
        self.assertEqual(json.loads(plain)["data"]["status"], "active")

    def test_token_signature_algorithm_binding_and_expiry(self):
        enc = lambda v: (
            base64.urlsafe_b64encode(json.dumps(v).encode()).decode().rstrip("=")
        )
        header, payload = (
            enc({"alg": "HS256"}),
            enc({"flow_token": "festive.test", "exp": 9999999999}),
        )
        signature = (
            base64.urlsafe_b64encode(
                hmac.new(
                    b"test-secret", f"{header}.{payload}".encode(), hashlib.sha256
                ).digest()
            )
            .decode()
            .rstrip("=")
        )
        request = {
            "flow_token": "festive.test",
            "flow_token_signature": f"{header}.{payload}.{signature}",
        }
        self.assertTrue(endpoint.verify_token_signature(request, "test-secret"))
        request["flow_token"] = "festive.someone-else"
        self.assertFalse(endpoint.verify_token_signature(request, "test-secret"))
        self.assertFalse(
            endpoint.verify_token_signature(
                {"flow_token_signature": "bad"}, "test-secret"
            )
        )

    def test_endpoint_off_and_unsigned(self):
        client = TestClient(app)
        with patch.dict(os.environ, {"FESTIVE_RUNS_ENABLED": "false"}):
            self.assertEqual(client.post("/festive/flows", json={}).status_code, 404)
        with (
            patch.dict(os.environ, {"FESTIVE_RUNS_ENABLED": "true"}),
            patch.object(endpoint, "WHATSAPP_APP_SECRET", "test-secret"),
        ):
            self.assertEqual(client.post("/festive/flows", json={}).status_code, 432)

    def test_signed_encrypted_healthcheck_and_decryption_error(self):
        client = TestClient(app)
        body, aes, iv = self.envelope({"version": "4.0", "action": "ping"})
        for payload, status in ((body, 200), ({}, 421)):
            raw = json.dumps(payload).encode()
            signature = (
                "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
            )
            with (
                patch.dict(
                    os.environ,
                    {
                        "FESTIVE_RUNS_ENABLED": "true",
                        "FESTIVE_FLOW_PRIVATE_KEY_PATH": "/fake/key",
                    },
                ),
                patch.object(endpoint, "WHATSAPP_APP_SECRET", "test-secret"),
                patch.object(Path, "read_bytes", return_value=self.pem),
            ):
                response = client.post(
                    "/festive/flows",
                    content=raw,
                    headers={"x-hub-signature-256": signature},
                )
            self.assertEqual(response.status_code, status)
            if status == 200:
                self.assertEqual(
                    json.loads(
                        AESGCM(aes).decrypt(
                            bytes(b ^ 255 for b in iv),
                            base64.b64decode(response.text),
                            None,
                        )
                    )["data"]["status"],
                    "active",
                )
