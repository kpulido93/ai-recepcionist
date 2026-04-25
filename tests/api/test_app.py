from __future__ import annotations

import platform

from fastapi.testclient import TestClient

from ai_recepcionista import __version__
from ai_recepcionista.api.app import app

client = TestClient(app)


def test_health_endpoint_returns_expected_payload() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "admin-api",
        "appName": "ai-recepcionista",
        "version": __version__,
        "environment": "development",
    }


def test_ready_endpoint_returns_green_checks() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "admin-api",
        "checks": {
            "config_loaded": True,
            "api_port_valid": True,
            "rtp_port_range_valid": True,
        },
    }


def test_version_endpoint_returns_runtime_information() -> None:
    response = client.get("/version")
    payload = response.json()

    assert response.status_code == 200
    assert payload["version"] == __version__
    assert payload["appName"] == "ai-recepcionista"
    assert payload["stasisAppName"] == "ai-recepcionista"
    assert payload["environment"] == "development"
    assert payload["pythonVersion"] == platform.python_version()
