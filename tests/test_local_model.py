"""Network-boundary tests for the local OVMS chat client."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import threading
import unittest
from unittest.mock import patch

import local_model


MODEL = "local-code-model"
MESSAGES = [{"role": "user", "content": "Write a short greeting."}]
SECRET_MARKER = "PROVIDER_BODY_MUST_NOT_LEAK"


def patch_response_format():
    """OVMS's documented json_schema wrapper for a bounded file patch."""
    return {"type": "json_schema", "json_schema": {"schema": {
        "type": "object", "properties": {"files": {
            "type": "array", "minItems": 1, "maxItems": 1,
            "items": {"type": "object", "properties": {
                "path": {"type": "string", "enum": ["solution.py"]},
                "content": {"type": "string", "minLength": 1},
            }, "required": ["path", "content"], "additionalProperties": False},
        }}, "required": ["files"], "additionalProperties": False,
    }}}


def good_body(*, model=MODEL, content="Hello.", finish_reason="stop", usage=None) -> bytes:
    if usage is None:
        usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    return json.dumps({
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": usage,
    }).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.request_count += 1
        self.server.last_path = self.path
        length = int(self.headers.get("Content-Length", "0"))
        self.server.last_body = self.rfile.read(length)
        self.send_response(self.server.response_status)
        if self.server.redirect_location is not None:
            self.send_header("Location", self.server.redirect_location)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.server.response_body)))
        self.end_headers()
        try:
            self.wfile.write(self.server.response_body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, _format, *_args):
        pass


class LocalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/v1/chat/completions"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.server.request_count = 0
        self.server.last_path = None
        self.server.last_body = None
        self.server.response_status = 200
        self.server.response_body = good_body()
        self.server.redirect_location = None

    def call(self, endpoint=None, messages=None, max_tokens=64, timeout_seconds=3.0):
        return local_model.chat_completion(endpoint or self.endpoint, MODEL,
                                           messages if messages is not None else MESSAGES,
                                           max_tokens, timeout_seconds)

    def call_format(self, response_format):
        return local_model.chat_completion(self.endpoint, MODEL, MESSAGES, 64, 3.0,
                                           response_format=response_format)

    def assert_error(self, code, call=None):
        with self.assertRaises(local_model.LocalModelError) as context:
            (call or self.call)()
        error = context.exception
        self.assertEqual(error.code, code)
        self.assertTrue(error.message)
        self.assertTrue(error.next_action)
        self.assertNotIn(SECRET_MARKER, json.dumps(error.report()))
        return error

    def test_success_returns_only_validated_fields(self):
        self.assertEqual(self.call(), {
            "model": MODEL, "content": "Hello.",
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        })
        self.assertEqual(self.server.request_count, 1)
        self.assertEqual(self.server.last_path, "/v1/chat/completions")
        request = json.loads(self.server.last_body)
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["messages"], MESSAGES)
        self.assertEqual(request["max_tokens"], 64)
        self.assertIs(request["stream"], False)
        self.assertNotIn("response_format", request)

    def test_json_schema_response_format_is_sent_unchanged(self):
        response_format = patch_response_format()
        self.assertEqual(self.call_format(response_format)["content"], "Hello.")
        self.assertEqual(json.loads(self.server.last_body)["response_format"], response_format)
        self.assertEqual(self.server.request_count, 1)

    def test_capture_retains_exact_request_and_raw_response(self):
        body = json.loads(good_body())
        body["id"] = "provider-response-id"
        self.server.response_body = json.dumps(body, indent=2).encode()
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture"
            result = local_model.chat_completion(self.endpoint, MODEL, MESSAGES, 64, 3,
                                                 capture_directory=capture)
            self.assertEqual(result["content"], "Hello.")
            self.assertEqual((capture / "request.json").read_bytes(), self.server.last_body)
            self.assertEqual((capture / "response.body").read_bytes(), self.server.response_body)
            metadata = json.loads((capture / "response.metadata.json").read_bytes())
            self.assertEqual(metadata["status"], 200)
            self.assertIs(metadata["complete"], True)
            self.assertEqual(json.loads((capture / "response.body").read_bytes())["choices"][0]["finish_reason"], "stop")
        self.assertEqual(self.server.request_count, 1)

    def test_capture_precedes_invalid_response_and_http_error(self):
        for status in (200, 500):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                capture = Path(temporary) / "capture"
                self.server.response_status = status
                self.server.response_body = SECRET_MARKER.encode()
                error = self.assert_error("invalid_response" if status == 200 else "http_error",
                    lambda: local_model.chat_completion(self.endpoint, MODEL, MESSAGES, 64, 3,
                                                        capture_directory=capture))
                self.assertEqual((capture / "response.body").read_bytes(), self.server.response_body)
                self.assertEqual(json.loads((capture / "response.metadata.json").read_bytes())["status"], status)
                self.assertNotIn(SECRET_MARKER, json.dumps(error.report()))

    def test_capture_refuses_existing_directory_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary)
            sentinel = capture / "keep"
            sentinel.write_bytes(b"original evidence")
            self.assert_error("capture_failed", lambda: local_model.chat_completion(
                self.endpoint, MODEL, MESSAGES, 64, 3, capture_directory=capture))
            self.assertEqual(sentinel.read_bytes(), b"original evidence")
        self.assertEqual(self.server.request_count, 0)

    def test_capture_marks_oversized_response_as_incomplete(self):
        self.server.response_body = b"x" * (local_model.MAX_RESPONSE_BYTES + 100)
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture"
            self.assert_error("response_too_large", lambda: local_model.chat_completion(
                self.endpoint, MODEL, MESSAGES, 64, 3, capture_directory=capture))
            self.assertEqual((capture / "response.body").stat().st_size, local_model.MAX_RESPONSE_BYTES + 1)
            self.assertIs(json.loads((capture / "response.metadata.json").read_bytes())["complete"], False)

    def test_capture_records_connection_failure_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = Path(temporary) / "capture"
            with patch.object(local_model.urllib.request, "build_opener") as factory:
                factory.return_value.open.side_effect = OSError("private connection detail")
                self.assert_error("connection_failed", lambda: local_model.chat_completion(
                    self.endpoint, MODEL, MESSAGES, 64, 3, capture_directory=capture))
                self.assertEqual(factory.return_value.open.call_count, 1)
            self.assertTrue((capture / "request.json").is_file())
            error = json.loads((capture / "transport-error.json").read_bytes())
            self.assertEqual(error["code"], "connection_failed")
            self.assertNotIn("private connection detail", json.dumps(error))

    def test_capture_write_failure_stops_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(local_model, "_capture_write", side_effect=OSError("disk full")):
                self.assert_error("capture_failed", lambda: local_model.chat_completion(
                    self.endpoint, MODEL, MESSAGES, 64, 3, capture_directory=Path(temporary) / "capture"))
        self.assertEqual(self.server.request_count, 0)

    def test_invalid_response_formats_fail_before_network(self):
        valid = patch_response_format()
        invalid = [
            [],
            {"type": "json_object"},
            {"type": "json_schema", "json_schema": {}},
            {"type": "json_schema", "json_schema": {"schema": valid["json_schema"]["schema"], "extra": 1}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "array", "items": {"type": "string"}}}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "object", "$ref": "http://remote.example/schema"}}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {
                "x": {"type": "string"}}, "required": ["missing"]}}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {
                "x": {"type": "string", "enum": [["bad"]]}}}}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {
                "x": {"type": "string"}}, "additionalProperties": "false"}}},
            {"type": "json_schema", "json_schema": {"schema": {"type": "object", "properties": {
                "x": {"type": "string"}}, "required": ["x", "x"]}}},
        ]
        for response_format in invalid:
            with self.subTest(response_format=response_format):
                self.assert_error("invalid_response_format",
                                  lambda: self.call_format(response_format))
        self.assertEqual(self.server.request_count, 0)

    def test_response_format_depth_and_bytes_are_bounded(self):
        deep = {"type": "string"}
        for _ in range(10):
            deep = {"type": "array", "items": deep}
        self.assert_error("invalid_response_format", lambda: self.call_format(
            {"type": "json_schema", "json_schema": {"schema": {
                "type": "object", "properties": {"deep": deep}}}}))
        wide = {f"field_{i}": {"type": "string", "description": "x" * 256}
                for i in range(60)}
        self.assert_error("invalid_response_format", lambda: self.call_format(
            {"type": "json_schema", "json_schema": {"schema": {
                "type": "object", "properties": wide}}}))
        self.assertEqual(self.server.request_count, 0)

    def test_v3_and_localhost_connect_to_loopback(self):
        endpoint = f"http://localhost:{self.server.server_port}/v3/chat/completions"
        self.assertEqual(self.call(endpoint=endpoint)["content"], "Hello.")
        self.assertEqual(self.server.last_path, "/v3/chat/completions")

    def test_remote_and_ambiguous_endpoints_fail_before_network(self):
        invalid = [
            f"http://127.0.0.2:{self.server.server_port}/v1/chat/completions",
            f"http://localhost.evil.test:{self.server.server_port}/v1/chat/completions",
            f"https://127.0.0.1:{self.server.server_port}/v1/chat/completions",
            f"http://user:password@127.0.0.1:{self.server.server_port}/v1/chat/completions",
            f"{self.endpoint}?token=private", f"{self.endpoint}#frag",
            f"{self.endpoint}?", f"{self.endpoint}#",
            f"http://127.0.0.1:{self.server.server_port}/other",
            "http://127.0.0.1:99999/v1/chat/completions",
        ]
        for endpoint in invalid:
            with self.subTest(endpoint=endpoint):
                self.assert_error("invalid_endpoint", lambda: self.call(endpoint=endpoint))
        self.assertEqual(self.server.request_count, 0)

    def test_proxy_environment_is_ignored(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                     "http_proxy": "http://127.0.0.1:1",
                                     "NO_PROXY": "", "no_proxy": ""}):
            self.assertEqual(self.call()["content"], "Hello.")
        self.assertEqual(self.server.request_count, 1)

    def test_redirect_is_not_followed(self):
        self.server.response_status = 302
        self.server.redirect_location = "https://remote.example/collect"
        self.server.response_body = SECRET_MARKER.encode()
        self.assert_error("redirect_blocked")
        self.assertEqual(self.server.request_count, 1)

    def test_http_error_is_safe_and_is_not_retried(self):
        self.server.response_status = 503
        self.server.response_body = SECRET_MARKER.encode()
        error = self.assert_error("http_error")
        self.assertIn("503", error.message)
        self.assertEqual(self.server.request_count, 1)

    def test_invalid_request_bounds_fail_before_network(self):
        self.assert_error("invalid_max_tokens", lambda: self.call(max_tokens=0))
        self.assert_error("invalid_max_tokens", lambda: self.call(max_tokens=True))
        self.assert_error("invalid_timeout", lambda: self.call(timeout_seconds=float("inf")))
        self.assert_error("invalid_timeout", lambda: self.call(timeout_seconds=0.1))
        self.assert_error("invalid_messages", lambda: self.call(messages=[]))
        self.assert_error("invalid_messages", lambda: self.call(messages=[{"role": "tool", "content": "x"}]))
        self.assert_error("invalid_messages", lambda: self.call(messages=[{"role": "user", "content": "x", "secret": "x"}]))
        self.assertEqual(self.server.request_count, 0)

    def test_oversized_request_fails_before_network(self):
        messages = [{"role": "user", "content": "x" * local_model.MAX_MESSAGE_CHARS} for _ in range(5)]
        self.assert_error("request_too_large", lambda: self.call(messages=messages))
        self.assertEqual(self.server.request_count, 0)

    def test_oversized_response_is_rejected(self):
        self.server.response_body = b"x" * (local_model.MAX_RESPONSE_BYTES + 1)
        self.assert_error("response_too_large")
        self.assertEqual(self.server.request_count, 1)

    def test_malformed_nonfinite_and_duplicate_json_are_rejected(self):
        for body in (b"not json", b"[]", b'{"x": NaN}', b'{"x": 1e999}', b'{"x": 1, "x": 2}'):
            with self.subTest(body=body):
                self.server.response_body = body
                self.assert_error("invalid_response")

    def test_wrong_model_is_rejected(self):
        self.server.response_body = good_body(model="different-model")
        self.assert_error("model_mismatch")

    def test_missing_content_or_incomplete_choice_is_rejected(self):
        self.server.response_body = good_body(content="")
        self.assert_error("invalid_response")
        self.server.response_body = good_body(finish_reason="length")
        self.assert_error("incomplete_response")

    def test_usage_must_be_present_and_consistent(self):
        for usage in ({}, {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 8},
                      {"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3}):
            with self.subTest(usage=usage):
                self.server.response_body = good_body(usage=usage)
                self.assert_error("invalid_response")

    def test_cli_probe_emits_one_synthetic_completion(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(local_model.__file__)), "probe",
             "--endpoint", self.endpoint, "--model", MODEL,
             "--max-tokens", "16", "--timeout-seconds", "3"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["content"], "Hello.")
        self.assertEqual(output["model"], MODEL)
        self.assertEqual(self.server.request_count, 1)
        request = json.loads(self.server.last_body)
        self.assertEqual(request["messages"], [{"role": "user", "content": "Reply briefly with LOCAL_MODEL_PROBE_OK."}])

    def test_cli_failure_has_safe_json_and_nonzero_exit(self):
        self.server.response_status = 500
        self.server.response_body = SECRET_MARKER.encode()
        result = subprocess.run(
            [sys.executable, "-B", str(Path(local_model.__file__)), "probe",
             "--endpoint", self.endpoint, "--model", MODEL],
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr)["code"], "http_error")
        self.assertNotIn(SECRET_MARKER, result.stderr)
        self.assertEqual(self.server.request_count, 1)


if __name__ == "__main__":
    unittest.main()
