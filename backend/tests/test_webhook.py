"""Tests for github_utils/webhook.py — signature verification.

Locks down a specific security property: once GITHUB_WEBHOOK_SECRET is
configured, a request missing the X-Hub-Signature-256 header must be
rejected rather than silently accepted as unauthenticated.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from main import app

PAYLOAD = {
    "action": "opened",
    "number": 1,
    "pull_request": {"base": {"sha": "a"}, "head": {"sha": "b"}},
    "repository": {"owner": {"login": "octocat"}, "name": "hello-world"},
}


def _signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def client():
    return TestClient(app)


def test_missing_signature_is_rejected_when_secret_configured(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")

    response = client.post(
        "/webhook",
        json=PAYLOAD,
        headers={"X-GitHub-Event": "pull_request"},
    )

    assert response.status_code == 401


def test_invalid_signature_is_rejected(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")

    response = client.post(
        "/webhook",
        json=PAYLOAD,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )

    assert response.status_code == 401


def test_valid_signature_is_accepted(client, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    body = json.dumps(PAYLOAD).encode()

    response = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": _signature(body, "test-secret"),
        },
    )

    assert response.status_code != 401
