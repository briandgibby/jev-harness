#!/usr/bin/env python3
"""Bounded OpenAI-compatible chat client for a local OVMS model.

``endpoint`` is the complete /v1/chat/completions or /v3/chat/completions URL.
Only an IPv4 loopback connection is made, including when the caller spells the
host ``localhost``. The module sends one request and never retries.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


MAX_REQUEST_BYTES = 64_000
MAX_RESPONSE_BYTES = 256_000
MAX_RESPONSE_FORMAT_BYTES = 16_384
MAX_SCHEMA_DEPTH = 8
MAX_SCHEMA_NODES = 64
MAX_MESSAGES = 16
MAX_MESSAGE_CHARS = 16_000
MAX_CONTENT_CHARS = 32_000
MAX_MODEL_CHARS = 200
MAX_TOKENS = 4_096
MAX_USAGE_TOKENS = 10_000_000
MIN_TIMEOUT_SECONDS = 0.5
MAX_TIMEOUT_SECONDS = 120.0
_CHAT_PATHS = frozenset({"/v1/chat/completions", "/v3/chat/completions"})
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*\Z")
_SCHEMA_PROPERTY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")


class LocalModelError(Exception):
    """An actionable error with no provider body, request text, or credential."""

    def __init__(self, code: str, message: str, next_action: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.next_action = next_action

    def report(self) -> dict:
        return {
            "status": "failed",
            "code": self.code,
            "message": self.message,
            "next_action": self.next_action,
        }


def _fail(code: str, message: str, action: str) -> None:
    raise LocalModelError(code, message, action)


def _loopback_url(endpoint: str) -> str:
    if type(endpoint) is not str or not endpoint or len(endpoint) > 256 or endpoint != endpoint.strip():
        _fail("invalid_endpoint", "endpoint must be a short local HTTP chat-completions URL.",
              "Set endpoint to http://127.0.0.1:<port>/v1/chat/completions or /v3/chat/completions.")
    try:
        parts = urllib.parse.urlsplit(endpoint)
        port = parts.port
        host = parts.hostname
    except ValueError:
        _fail("invalid_endpoint", "endpoint has an invalid host or port.",
              "Set endpoint to a valid 127.0.0.1 or localhost HTTP URL and port.")
    if (parts.scheme != "http" or host not in {"127.0.0.1", "localhost"}
            or parts.username is not None or parts.password is not None
            or "?" in endpoint or "#" in endpoint or parts.path not in _CHAT_PATHS):
        _fail("invalid_endpoint", "endpoint must identify a local HTTP chat-completions path without credentials, query, or fragment.",
              "Use http://127.0.0.1:<port>/v1/chat/completions or /v3/chat/completions.")
    if port is None:
        port = 80
    if port < 1 or port > 65535:
        _fail("invalid_endpoint", "endpoint port is outside 1..65535.",
              "Set a valid local service port.")
    # Resolve localhost here, rather than trusting a mutable hosts/DNS entry.
    return f"http://127.0.0.1:{port}{parts.path}"


def _invalid_format() -> None:
    _fail("invalid_response_format", "response_format is not a supported bounded JSON schema.",
          "Use the OVMS json_schema wrapper with a bounded object schema and supported keywords.")


def _schema_bound(value, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _validate_schema_node(node, depth: int, count: list[int]) -> None:
    count[0] += 1
    if depth > MAX_SCHEMA_DEPTH or count[0] > MAX_SCHEMA_NODES or type(node) is not dict:
        _invalid_format()
    node_type = node.get("type")
    common = {"type", "title", "description"}
    specific = {
        "object": {"properties", "required", "additionalProperties"},
        "array": {"items", "minItems", "maxItems"},
        "string": {"enum", "minLength", "maxLength"},
        "integer": set(), "number": set(), "boolean": set(), "null": set(),
    }
    if type(node_type) is not str or node_type not in specific or set(node) - common - specific[node_type]:
        _invalid_format()
    for field in ("title", "description"):
        if field in node:
            value = node[field]
            if type(value) is not str or len(value) > 256:
                _invalid_format()
            try:
                value.encode("utf-8")
            except UnicodeError:
                _invalid_format()
    if node_type == "object":
        properties = node.get("properties")
        if type(properties) is not dict or not 1 <= len(properties) <= MAX_SCHEMA_NODES:
            _invalid_format()
        if any(type(name) is not str or not _SCHEMA_PROPERTY.fullmatch(name)
               for name in properties):
            _invalid_format()
        required = node.get("required", [])
        if (type(required) is not list or len(required) > len(properties)
                or any(type(name) is not str or name not in properties for name in required)
                or len(set(required)) != len(required)):
            _invalid_format()
        if "additionalProperties" in node and type(node["additionalProperties"]) is not bool:
            _invalid_format()
        for child in properties.values():
            _validate_schema_node(child, depth + 1, count)
    elif node_type == "array":
        if "items" not in node:
            _invalid_format()
        lower, upper = node.get("minItems", 0), node.get("maxItems", 1_000)
        if not _schema_bound(lower, 1_000) or not _schema_bound(upper, 1_000) or lower > upper:
            _invalid_format()
        _validate_schema_node(node["items"], depth + 1, count)
    elif node_type == "string":
        lower, upper = node.get("minLength", 0), node.get("maxLength", MAX_CONTENT_CHARS)
        if (not _schema_bound(lower, MAX_CONTENT_CHARS)
                or not _schema_bound(upper, MAX_CONTENT_CHARS) or lower > upper):
            _invalid_format()
        if "enum" in node:
            values = node["enum"]
            if (type(values) is not list or not 1 <= len(values) <= 32
                    or any(type(value) is not str or not value or len(value) > 256
                           for value in values)):
                _invalid_format()
            try:
                if len(set(values)) != len(values):
                    _invalid_format()
                for value in values:
                    value.encode("utf-8")
            except UnicodeError:
                _invalid_format()


def _validate_response_format(response_format) -> dict | None:
    if response_format is None:
        return None
    if (type(response_format) is not dict or set(response_format) != {"type", "json_schema"}
            or response_format["type"] != "json_schema"):
        _invalid_format()
    wrapper = response_format["json_schema"]
    if type(wrapper) is not dict or set(wrapper) != {"schema"}:
        _invalid_format()
    schema = wrapper["schema"]
    if type(schema) is not dict or schema.get("type") != "object":
        _invalid_format()
    _validate_schema_node(schema, 0, [0])
    try:
        encoded = json.dumps(response_format, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError):
        _invalid_format()
    if len(encoded) > MAX_RESPONSE_FORMAT_BYTES:
        _invalid_format()
    return response_format


def _validate_request(model_id, messages, max_tokens, timeout_seconds,
                      response_format=None) -> bytes:
    if (type(model_id) is not str or len(model_id) > MAX_MODEL_CHARS
            or not _MODEL_ID.fullmatch(model_id)):
        _fail("invalid_model", "model_id must be a stable, printable model name of at most 200 characters.",
              "Set model_id to the exact ID exposed by the local server.")
    if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_TOKENS:
        _fail("invalid_max_tokens", f"max_tokens must be an integer in 1..{MAX_TOKENS}.",
              "Set max_tokens within the named range.")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
        _fail("invalid_timeout", f"timeout_seconds must be finite and in {MIN_TIMEOUT_SECONDS}..{MAX_TIMEOUT_SECONDS}.",
              "Set timeout_seconds within the named range.")
    if type(messages) is not list or not 1 <= len(messages) <= MAX_MESSAGES:
        _fail("invalid_messages", f"messages must contain 1..{MAX_MESSAGES} chat messages.",
              "Provide a bounded list of system, user, or assistant messages.")
    for index, message in enumerate(messages):
        if type(message) is not dict or set(message) != {"role", "content"}:
            _fail("invalid_messages", f"messages[{index}] must contain exactly role and content.",
                  "Remove unsupported message fields and provide text content.")
        if message["role"] not in ("system", "user", "assistant") or type(message["role"]) is not str:
            _fail("invalid_messages", f"messages[{index}].role is unsupported.",
                  "Use system, user, or assistant.")
        content = message["content"]
        if type(content) is not str or not content or len(content) > MAX_MESSAGE_CHARS:
            _fail("invalid_messages", f"messages[{index}].content must contain 1..{MAX_MESSAGE_CHARS} characters.",
                  "Provide bounded nonempty text content.")
    payload = {"model": model_id, "messages": messages, "max_tokens": max_tokens, "stream": False}
    validated_format = _validate_response_format(response_format)
    if validated_format is not None:
        payload["response_format"] = validated_format
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise LocalModelError("invalid_messages", "messages contain invalid Unicode or JSON.",
                              "Replace invalid text and retry.") from exc
    if len(encoded) > MAX_REQUEST_BYTES:
        _fail("request_too_large", f"The request exceeds {MAX_REQUEST_BYTES} bytes.",
              "Reduce the number or size of messages.")
    return encoded


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("non-finite JSON constant")


def _finite_json(value, depth=0):
    if depth > 50:
        raise ValueError("JSON nesting is too deep")
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return
    if type(value) is str:
        value.encode("utf-8")
        return
    if type(value) is list:
        for item in value:
            _finite_json(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            _finite_json(key, depth + 1)
            _finite_json(item, depth + 1)
        return
    raise ValueError("unsupported JSON value")


def _validated_response(raw: bytes, model_id: str) -> dict:
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
                          parse_constant=_reject_constant)
        _finite_json(body)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise LocalModelError("invalid_response", "The local model returned malformed or unsupported JSON.",
                              "Check the local server and its OpenAI-compatible response format.") from exc
    if type(body) is not dict:
        _fail("invalid_response", "The local model response is not a JSON object.",
              "Check the local server chat-completions response format.")
    if body.get("model") != model_id:
        _fail("model_mismatch", "The response model does not match the requested model_id.",
              "Pin the configured model_id to the exact local server model and retry.")
    choices = body.get("choices")
    if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
        _fail("invalid_response", "The response must contain exactly one choice.",
              "Check the local server chat-completions response format.")
    choice = choices[0]
    message = choice.get("message")
    if (type(message) is not dict or message.get("role") != "assistant"
            or type(message.get("content")) is not str):
        _fail("invalid_response", "The response choice has no assistant text content.",
              "Configure a text chat model that returns assistant content.")
    content = message["content"]
    if not content or len(content) > MAX_CONTENT_CHARS:
        _fail("invalid_response", f"Assistant content must contain 1..{MAX_CONTENT_CHARS} characters.",
              "Reduce the completion limit or correct the local server response.")
    if choice.get("finish_reason") != "stop":
        _fail("incomplete_response", "The local model did not report a completed response.",
              "Use an adequate max_tokens limit or inspect the local model configuration.")
    usage = body.get("usage")
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    if (type(usage) is not dict or any(type(usage.get(key)) is not int
                                      or not 0 <= usage[key] <= MAX_USAGE_TOKENS for key in fields)
            or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]):
        _fail("invalid_response", "The response has missing or inconsistent token usage.",
              "Enable token usage reporting in the local server and retry.")
    return {"model": model_id, "content": content,
            "usage": {key: usage[key] for key in fields}}


def chat_completion(endpoint: str, model_id: str, messages: list[dict],
                    max_tokens: int, timeout_seconds: float,
                    response_format: dict | None = None) -> dict:
    """Send one bounded local request and return {model, content, usage}."""
    url = _loopback_url(endpoint)
    payload = _validate_request(model_id, messages, max_tokens, timeout_seconds,
                                response_format)
    request = urllib.request.Request(url, data=payload, method="POST", headers={
        "Accept": "application/json", "Content-Type": "application/json",
    })
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                _fail("http_error", f"The local model returned HTTP {response.status}.",
                      "Check the local server endpoint and model, then retry manually.")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        if 300 <= exc.code < 400:
            raise LocalModelError("redirect_blocked", "The local model endpoint returned a redirect.",
                                  "Use the final local chat-completions URL directly.") from None
        raise LocalModelError("http_error", f"The local model returned HTTP {exc.code}.",
                              "Check the local server endpoint and model, then retry manually.") from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        raise LocalModelError("connection_failed", "The local model endpoint could not be reached.",
                              "Start the local model server and verify its loopback port.") from None
    if len(raw) > MAX_RESPONSE_BYTES:
        _fail("response_too_large", f"The response exceeds {MAX_RESPONSE_BYTES} bytes.",
              "Reduce max_tokens or correct the local server response.")
    return _validated_response(raw, model_id)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Probe one bounded local chat completion.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    probe = subcommands.add_parser("probe", help="send one synthetic completion")
    probe.add_argument("--endpoint", required=True, help="exact local /v1 or /v3 chat-completions URL")
    probe.add_argument("--model", required=True, help="exact local model ID")
    probe.add_argument("--max-tokens", type=int, default=64)
    probe.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)
    try:
        result = chat_completion(
            args.endpoint, args.model,
            [{"role": "user", "content": "Reply briefly with LOCAL_MODEL_PROBE_OK."}],
            args.max_tokens, args.timeout_seconds,
        )
    except LocalModelError as exc:
        print(json.dumps(exc.report(), sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "ok", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
