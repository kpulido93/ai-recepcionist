from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IVR_LISTEN_SECONDS = 5
DEFAULT_SAMPLE_RATE = 8000
DEFAULT_EARLY_DETECTION_ENABLED = True
DEFAULT_EARLY_DETECTION_MIN_AUDIO_MS = 250
DEFAULT_EARLY_DETECTION_MIN_CHARS = 2
DEFAULT_VAD_ENABLED = True
DEFAULT_MIN_SPEECH_MS = 250
DEFAULT_SILENCE_AFTER_SPEECH_MS = 700
DEFAULT_RMS_SPEECH_THRESHOLD = 250.0
DEFAULT_MASK_PHONE_NUMBERS = True
DEFAULT_DEBUG_AUDIO_DUMP_ENABLED = False
DEFAULT_DEBUG_AUDIO_DUMP_DIR = "/tmp"


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
    sample_rate: int
    retry_attempts: int
    default_intent: str
    allow_dtmf_fallback: bool
    early_detection_enabled: bool
    early_detection_min_audio_ms: int
    early_detection_min_chars: int
    vad_enabled: bool
    min_speech_ms: int
    silence_after_speech_ms: int
    rms_speech_threshold: float
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
    debug_audio_dump_enabled: bool
    debug_audio_dump_dir: str
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
    ivr_config = _get_section(raw_config, "ivr")
    asterisk_config = _get_section(raw_config, "asterisk")
    vosk_config = _get_section(raw_config, "vosk")
    logging_config = _get_section(raw_config, "logging")
    sample_rate = _resolve_sample_rate(ivr_config, vosk_config)

    try:
        return AppConfig(
            audio=AudioSettings(
                min_rms=float(raw_config.get("audio", {}).get("min_rms", 150.0)),
            ),
            ivr=IvrSettings(
                listen_seconds=int(ivr_config.get("listen_seconds", DEFAULT_IVR_LISTEN_SECONDS)),
                sample_rate=sample_rate,
                retry_attempts=int(ivr_config["retry_attempts"]),
                default_intent=str(ivr_config["default_intent"]).upper(),
                allow_dtmf_fallback=bool(ivr_config["allow_dtmf_fallback"]),
                early_detection_enabled=bool(
                    ivr_config.get("early_detection_enabled", DEFAULT_EARLY_DETECTION_ENABLED)
                ),
                early_detection_min_audio_ms=int(
                    ivr_config.get(
                        "early_detection_min_audio_ms",
                        DEFAULT_EARLY_DETECTION_MIN_AUDIO_MS,
                    )
                ),
                early_detection_min_chars=int(
                    ivr_config.get("early_detection_min_chars", DEFAULT_EARLY_DETECTION_MIN_CHARS)
                ),
                vad_enabled=bool(ivr_config.get("vad_enabled", DEFAULT_VAD_ENABLED)),
                min_speech_ms=int(ivr_config.get("min_speech_ms", DEFAULT_MIN_SPEECH_MS)),
                silence_after_speech_ms=int(
                    ivr_config.get(
                        "silence_after_speech_ms",
                        DEFAULT_SILENCE_AFTER_SPEECH_MS,
                    )
                ),
                rms_speech_threshold=float(
                    ivr_config.get("rms_speech_threshold", DEFAULT_RMS_SPEECH_THRESHOLD)
                ),
                max_dtmf_wait_ms=int(ivr_config["max_dtmf_wait_ms"]),
                dtmf_map={
                    str(key): str(value).upper() for key, value in ivr_config["dtmf_map"].items()
                },
            ),
            asterisk=AsteriskSettings(
                app_name=str(asterisk_config["app_name"]),
                channel_variable_name=str(asterisk_config["channel_variable_name"]),
                transfer_context=str(asterisk_config["transfer_context"]),
                lawyer_destination_type=str(asterisk_config["lawyer_destination_type"]),
                lawyer_destination=str(asterisk_config["lawyer_destination"]),
                final_disposition_yes=str(asterisk_config["final_disposition_yes"]),
                final_disposition_no=str(asterisk_config["final_disposition_no"]),
                final_disposition_unknown=str(asterisk_config["final_disposition_unknown"]),
            ),
            vosk=VoskSettings(
                websocket_url=str(vosk_config["websocket_url"]),
                sample_rate=sample_rate,
                audio_format=str(vosk_config["audio_format"]),
                language=str(vosk_config["language"]),
                websocket_timeout_seconds=int(vosk_config["websocket_timeout_seconds"]),
            ),
            logging=LoggingSettings(
                enabled=bool(logging_config["enabled"]),
                log_level=str(logging_config["log_level"]).upper(),
                log_path=str(logging_config["log_path"]),
                log_transcript=bool(logging_config.get("log_transcript", False)),
                mask_phone_numbers=bool(
                    logging_config.get("mask_phone_numbers", DEFAULT_MASK_PHONE_NUMBERS)
                ),
                debug_audio_dump_enabled=_resolve_debug_audio_dump_enabled(
                    raw_config,
                    logging_config,
                ),
                debug_audio_dump_dir=_resolve_debug_audio_dump_dir(
                    raw_config,
                    logging_config,
                ),
                rotate_max_bytes=int(logging_config.get("rotate_max_bytes", 10485760)),
                rotate_backup_count=int(logging_config.get("rotate_backup_count", 10)),
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
    _set_sample_rate_from_env(config_data)
    _set_if_env(config_data, ("vosk", "websocket_url"), "VOSK_WEBSOCKET_URL")
    _set_if_env(
        config_data,
        ("vosk", "websocket_timeout_seconds"),
        "VOSK_WEBSOCKET_TIMEOUT_SECONDS",
        transform=int,
    )
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


def _get_section(config_data: dict[str, Any], section_name: str) -> dict[str, Any]:
    section = config_data.get(section_name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"La seccion '{section_name}' debe ser un objeto YAML.")
    return section


def _resolve_sample_rate(ivr_config: dict[str, Any], vosk_config: dict[str, Any]) -> int:
    return int(ivr_config.get("sample_rate", vosk_config.get("sample_rate", DEFAULT_SAMPLE_RATE)))


def _resolve_debug_audio_dump_enabled(
    config_data: dict[str, Any],
    logging_config: dict[str, Any],
) -> bool:
    debug_config = _get_section(config_data, "debug")
    if "audio_dump_enabled" in debug_config:
        return bool(debug_config["audio_dump_enabled"])
    return bool(
        logging_config.get(
            "debug_audio_dump_enabled",
            DEFAULT_DEBUG_AUDIO_DUMP_ENABLED,
        )
    )


def _resolve_debug_audio_dump_dir(
    config_data: dict[str, Any],
    logging_config: dict[str, Any],
) -> str:
    debug_config = _get_section(config_data, "debug")
    if "audio_dump_dir" in debug_config:
        return str(debug_config["audio_dump_dir"])
    return str(logging_config.get("debug_audio_dump_dir", DEFAULT_DEBUG_AUDIO_DUMP_DIR))


def _set_sample_rate_from_env(config_data: dict[str, Any]) -> None:
    env_value = os.getenv("IVR_SAMPLE_RATE")
    if env_value is None:
        env_value = os.getenv("VOSK_SAMPLE_RATE")
    if env_value is None:
        return

    sample_rate = int(env_value)
    _set_config_value(config_data, ("ivr", "sample_rate"), sample_rate)
    _set_config_value(config_data, ("vosk", "sample_rate"), sample_rate)


def _set_if_env(
    config_data: dict[str, Any],
    path_segments: tuple[str, str],
    env_name: str,
    transform: Callable[[str], Any] | None = None,
) -> None:
    env_value = os.getenv(env_name)
    if env_value is None:
        return

    if transform is not None:
        value: Any = transform(env_value)
    else:
        value = env_value

    _set_config_value(config_data, path_segments, value)


def _set_config_value(
    config_data: dict[str, Any],
    path_segments: tuple[str, str],
    value: Any,
) -> None:
    section = config_data.get(path_segments[0])
    if not isinstance(section, dict):
        section = {}
        config_data[path_segments[0]] = section
    section[path_segments[1]] = value


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"Valor booleano invalido: {value}")
