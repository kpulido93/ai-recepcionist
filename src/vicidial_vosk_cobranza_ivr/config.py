from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised when project configuration cannot be loaded."""


@dataclass(frozen=True)
class RuntimePaths:
    config_path: Path
    intents_path: Path
    logging_path: Path


@dataclass(frozen=True)
class AudioSettings:
    min_rms: float


@dataclass(frozen=True)
class IvrSettings:
    listen_seconds: int
    retry_attempts: int
    default_intent: str
    allow_dtmf_fallback: bool
    max_dtmf_wait_ms: int
    dtmf_map: dict[str, str]


@dataclass(frozen=True)
class AsteriskSettings:
    app_name: str
    channel_variable_name: str
    transfer_context: str
    lawyer_destination_type: str
    lawyer_destination: str
    final_disposition_yes: str
    final_disposition_no: str
    final_disposition_unknown: str


@dataclass(frozen=True)
class VoskSettings:
    websocket_url: str
    sample_rate: int
    audio_format: str
    language: str
    websocket_timeout_seconds: int


@dataclass(frozen=True)
class LoggingSettings:
    enabled: bool
    log_level: str
    log_path: str
    log_transcript: bool
    mask_phone_numbers: bool
    rotate_max_bytes: int
    rotate_backup_count: int


@dataclass(frozen=True)
class AppConfig:
    audio: AudioSettings
    ivr: IvrSettings
    asterisk: AsteriskSettings
    vosk: VoskSettings
    logging: LoggingSettings
    intents: dict[str, list[str]]


def resolve_runtime_paths(
    config_path: Path | None = None,
    intents_path: Path | None = None,
    logging_path: Path | None = None,
) -> RuntimePaths:
    # In production the AGI script may be copied to /var/lib/asterisk/agi-bin, so
    # repo-relative paths stop being reliable. Absolute env overrides keep config,
    # intents and logging paths stable regardless of where Asterisk executes the AGI.
    return RuntimePaths(
        config_path=_resolve_path(
            config_path,
            "VOSK_COBRANZA_CONFIG",
            PROJECT_ROOT / "config" / "ivr.yml",
        ),
        intents_path=_resolve_path(
            intents_path,
            "VOSK_COBRANZA_INTENTS",
            PROJECT_ROOT / "config" / "intents.yml",
        ),
        logging_path=_resolve_path(
            logging_path,
            "VOSK_COBRANZA_LOGGING",
            PROJECT_ROOT / "config" / "logging.yml",
        ),
    )


def load_app_config(config_path: Path, intents_path: Path) -> AppConfig:
    raw_config = _load_yaml_file(config_path)
    raw_intents = _load_yaml_file(intents_path)
    _apply_env_overrides(raw_config)

    try:
        return AppConfig(
            audio=AudioSettings(
                min_rms=float(raw_config.get("audio", {}).get("min_rms", 150.0)),
            ),
            ivr=IvrSettings(
                listen_seconds=int(raw_config["ivr"]["listen_seconds"]),
                retry_attempts=int(raw_config["ivr"]["retry_attempts"]),
                default_intent=str(raw_config["ivr"]["default_intent"]).upper(),
                allow_dtmf_fallback=bool(raw_config["ivr"]["allow_dtmf_fallback"]),
                max_dtmf_wait_ms=int(raw_config["ivr"]["max_dtmf_wait_ms"]),
                dtmf_map={
                    str(key): str(value).upper()
                    for key, value in raw_config["ivr"]["dtmf_map"].items()
                },
            ),
            asterisk=AsteriskSettings(
                app_name=str(raw_config["asterisk"]["app_name"]),
                channel_variable_name=str(raw_config["asterisk"]["channel_variable_name"]),
                transfer_context=str(raw_config["asterisk"]["transfer_context"]),
                lawyer_destination_type=str(raw_config["asterisk"]["lawyer_destination_type"]),
                lawyer_destination=str(raw_config["asterisk"]["lawyer_destination"]),
                final_disposition_yes=str(raw_config["asterisk"]["final_disposition_yes"]),
                final_disposition_no=str(raw_config["asterisk"]["final_disposition_no"]),
                final_disposition_unknown=str(raw_config["asterisk"]["final_disposition_unknown"]),
            ),
            vosk=VoskSettings(
                websocket_url=str(raw_config["vosk"]["websocket_url"]),
                sample_rate=int(raw_config["vosk"]["sample_rate"]),
                audio_format=str(raw_config["vosk"]["audio_format"]),
                language=str(raw_config["vosk"]["language"]),
                websocket_timeout_seconds=int(raw_config["vosk"]["websocket_timeout_seconds"]),
            ),
            logging=LoggingSettings(
                enabled=bool(raw_config["logging"]["enabled"]),
                log_level=str(raw_config["logging"]["log_level"]).upper(),
                log_path=str(raw_config["logging"]["log_path"]),
                log_transcript=bool(raw_config["logging"].get("log_transcript", False)),
                mask_phone_numbers=bool(raw_config["logging"]["mask_phone_numbers"]),
                rotate_max_bytes=int(raw_config["logging"].get("rotate_max_bytes", 10485760)),
                rotate_backup_count=int(raw_config["logging"].get("rotate_backup_count", 10)),
            ),
            intents={
                str(intent_name).upper(): [str(phrase) for phrase in phrase_list]
                for intent_name, phrase_list in raw_intents.items()
            },
        )
    except KeyError as exc:
        raise ConfigError(f"Falta la clave de configuracion: {exc}") from exc


def _resolve_path(path: Path | None, env_name: str, default_path: Path) -> Path:
    if path is not None:
        return path.resolve()

    env_value = os.getenv(env_name)
    if env_value:
        return Path(env_value).expanduser().resolve()

    return default_path.resolve()


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"No existe el archivo: {path}")

    with path.open("r", encoding="utf-8") as file_handler:
        data = yaml.safe_load(file_handler) or {}

    if not isinstance(data, dict):
        raise ConfigError(f"El YAML debe contener un objeto en la raiz: {path}")

    return data


def _apply_env_overrides(config_data: dict[str, Any]) -> None:
    _set_if_env(config_data, ("vosk", "websocket_url"), "VOSK_WEBSOCKET_URL")
    _set_if_env(config_data, ("vosk", "sample_rate"), "VOSK_SAMPLE_RATE", transform=int)
    _set_if_env(
        config_data,
        ("ivr", "listen_seconds"),
        "IVR_LISTEN_SECONDS",
        transform=int,
    )
    _set_if_env(config_data, ("audio", "min_rms"), "VOSK_MIN_RMS", transform=float)
    _set_if_env(config_data, ("logging", "log_level"), "LOG_LEVEL", transform=str.upper)
    _set_if_env(config_data, ("logging", "log_path"), "LOG_PATH")
    _set_if_env(config_data, ("logging", "log_transcript"), "LOG_TRANSCRIPT", transform=_parse_bool)
    _set_if_env(
        config_data,
        ("logging", "rotate_max_bytes"),
        "LOG_ROTATE_MAX_BYTES",
        transform=int,
    )
    _set_if_env(
        config_data,
        ("logging", "rotate_backup_count"),
        "LOG_ROTATE_BACKUP_COUNT",
        transform=int,
    )


def _set_if_env(
    config_data: dict[str, Any],
    path_segments: tuple[str, str],
    env_name: str,
    transform: Callable[[str], Any] | None = None,
) -> None:
    if path_segments[0] not in config_data or not isinstance(config_data[path_segments[0]], dict):
        config_data[path_segments[0]] = {}

    env_value = os.getenv(env_name)
    if env_value is None:
        return

    if transform is not None:
        value: Any = transform(env_value)
    else:
        value = env_value

    config_data[path_segments[0]][path_segments[1]] = value


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Valor booleano invalido: {value}")
