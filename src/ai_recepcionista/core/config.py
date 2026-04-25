from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .. import __version__

ENV_PREFIX = "AI_RECEPCIONISTA_"


def _get_env(name: str, default: str) -> str:
    return os.getenv(f"{ENV_PREFIX}{name}", default)


def _get_int_env(name: str, default: int) -> int:
    value = _get_env(name, str(default))
    try:
        return int(value)
    except ValueError as exc:
        message = f"{ENV_PREFIX}{name} must be an integer, got {value!r}"
        raise ValueError(message) from exc


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str
    environment: str
    version: str
    log_level: str
    api_host: str
    api_port: int
    stasis_app_name: str
    ari_base_url: str
    ari_username: str
    ari_password: str
    ami_host: str
    ami_port: int
    media_advertised_host: str
    media_rtp_start_port: int
    media_rtp_end_port: int
    callbacks_backend: str
    dispositions_backend: str
    audit_backend: str
    worker_heartbeat_seconds: int

    def validate(self) -> None:
        if self.api_port <= 0:
            raise ValueError("AI_RECEPCIONISTA_API_PORT must be a positive integer")
        if self.ami_port <= 0:
            raise ValueError("AI_RECEPCIONISTA_AMI_PORT must be a positive integer")
        if self.media_rtp_start_port <= 0 or self.media_rtp_end_port <= 0:
            raise ValueError("RTP ports must be positive integers")
        if self.media_rtp_start_port > self.media_rtp_end_port:
            raise ValueError("AI_RECEPCIONISTA_MEDIA_RTP_START_PORT must be <= END_PORT")
        if self.worker_heartbeat_seconds <= 0:
            raise ValueError("AI_RECEPCIONISTA_WORKER_HEARTBEAT_SECONDS must be positive")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        app_name=_get_env("APP_NAME", "ai-recepcionista"),
        environment=_get_env("ENVIRONMENT", "development"),
        version=_get_env("VERSION", __version__),
        log_level=_get_env("LOG_LEVEL", "INFO").upper(),
        api_host=_get_env("API_HOST", "0.0.0.0"),
        api_port=_get_int_env("API_PORT", 8000),
        stasis_app_name=_get_env("STASIS_APP_NAME", "ai-recepcionista"),
        ari_base_url=_get_env("ARI_BASE_URL", ""),
        ari_username=_get_env("ARI_USERNAME", ""),
        ari_password=_get_env("ARI_PASSWORD", ""),
        ami_host=_get_env("AMI_HOST", ""),
        ami_port=_get_int_env("AMI_PORT", 5038),
        media_advertised_host=_get_env("MEDIA_ADVERTISED_HOST", "127.0.0.1"),
        media_rtp_start_port=_get_int_env("MEDIA_RTP_START_PORT", 20000),
        media_rtp_end_port=_get_int_env("MEDIA_RTP_END_PORT", 20100),
        callbacks_backend=_get_env("CALLBACKS_BACKEND", "stub"),
        dispositions_backend=_get_env("DISPOSITIONS_BACKEND", "stub"),
        audit_backend=_get_env("AUDIT_BACKEND", "stub"),
        worker_heartbeat_seconds=_get_int_env("WORKER_HEARTBEAT_SECONDS", 30),
    )
    settings.validate()
    return settings
