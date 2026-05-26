#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


def _bootstrap_src_path() -> None:
    project_root = Path(__file__).resolve().parents[1]
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


OPTIONAL_ENV_FILE = Path("/etc/default/vicidial-vosk-cobranza-ivr")


def _load_optional_runtime_env() -> None:
    if not OPTIONAL_ENV_FILE.exists():
        return

    target_vars = ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID")
    if all(os.getenv(variable_name) for variable_name in target_vars):
        return

    try:
        env_lines = OPTIONAL_ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in env_lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in target_vars or os.getenv(key):
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


_bootstrap_src_path()
_load_optional_runtime_env()

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT  # noqa: E402
from vicidial_vosk_cobranza_ivr.name_audio_cache import (  # noqa: E402
    DEFAULT_ELEVENLABS_API_KEY_ENV,
    DEFAULT_ELEVENLABS_VOICE_ID_ENV,
    DEFAULT_NAME_AUDIO_CACHE_DIR,
    DEFAULT_NAME_AUDIO_PLAYBACK_PREFIX,
    build_name_audio_text,
    build_name_cache_key,
    get_cached_name_audio,
    get_or_generate_name_audio,
    normalize_name_audio_gender,
    normalize_person_name,
)


@dataclass(slots=True)
class NameAudioReport:
    status: str
    reason: str
    message: str
    generated: bool
    cache_hit: bool
    gender: str
    generated_text: str
    playback_path: str
    wav_path: str
    cache_dir: str
    normalized_name: str
    voice_id: str
    mirror_paths: tuple[str, ...]


def load_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
        config_data = yaml.safe_load(file_handler) or {}
    if not isinstance(config_data, dict):
        raise SystemExit("config/ivr.yml debe contener un objeto YAML.")
    return config_data


def build_playback_path(audio_path: Path | None, config: dict[str, object]) -> str:
    if audio_path is None:
        return ""
    name_audio_config = get_name_audio_config(config)
    playback_prefix = str(
        name_audio_config.get("playback_prefix", DEFAULT_NAME_AUDIO_PLAYBACK_PREFIX)
    ).strip("/")
    return f"{playback_prefix}/{audio_path.stem}"


def inspect_name_audio(
    client_name: str,
    config: dict[str, object],
    gender: str | None = None,
) -> NameAudioReport:
    name_audio_config = get_name_audio_config(config)
    normalized_name = normalize_person_name(client_name)
    normalized_gender = normalize_name_audio_gender(gender)
    cache_dir = resolve_cache_dir(name_audio_config)
    voice_id = resolve_voice_id(name_audio_config)

    if not client_name.strip():
        return build_report(
            status="invalid_name",
            reason="missing_name",
            message="Debes pasar un nombre. Ejemplo: python scripts/test_name_cache.py Kevin",
            config=config,
            cache_dir=cache_dir,
            normalized_name="",
            gender=normalized_gender,
            generated_text="",
            voice_id=voice_id,
        )

    if not normalized_name:
        return build_report(
            status="invalid_name",
            reason="empty_normalized_name",
            message="El nombre quedó vacío después de sanitizarlo.",
            config=config,
            cache_dir=cache_dir,
            normalized_name="",
            gender=normalized_gender,
            generated_text="",
            voice_id=voice_id,
        )

    if not bool(name_audio_config.get("enabled", False)):
        return build_report(
            status="disabled",
            reason="name_audio_disabled",
            message="La configuración name_audio.enabled está desactivada o no existe en ivr.yml.",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text="",
            voice_id=voice_id,
        )

    try:
        generated_text = build_name_audio_text(normalized_name, config, gender=normalized_gender)
    except ValueError as exc:
        return build_report(
            status=map_value_error_status(str(exc)),
            reason=map_value_error_reason(str(exc)),
            message=str(exc),
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text="",
            voice_id=voice_id,
        )

    api_key_env = resolve_api_key_env(name_audio_config)
    if not os.getenv(api_key_env, "").strip():
        return build_report(
            status="missing_api_key",
            reason="missing_api_key",
            message=f"Falta la variable de entorno {api_key_env}.",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
        )

    if not voice_id:
        voice_id_env = resolve_voice_id_env(name_audio_config)
        return build_report(
            status="invalid_config",
            reason="missing_voice_id",
            message=f"Falta voice_id en config y tampoco está seteada la variable {voice_id_env}.",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id="",
        )

    cache_dir_error = ensure_cache_dir(cache_dir)
    if cache_dir_error is not None:
        status, reason, message = cache_dir_error
        return build_report(
            status=status,
            reason=reason,
            message=message,
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
        )

    cached_path = get_cached_name_audio(normalized_name, config, gender=normalized_gender)

    strict_config = build_strict_config(config)
    try:
        audio_path = get_or_generate_name_audio(
            normalized_name,
            strict_config,
            gender=normalized_gender,
        )
    except PermissionError as exc:
        return build_report(
            status="error",
            reason="cache_dir_not_writable",
            message=f"No fue posible escribir en el directorio de caché: {exc}",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
        )
    except ValueError as exc:
        return build_report(
            status=map_value_error_status(str(exc)),
            reason=map_value_error_reason(str(exc)),
            message=str(exc),
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
        )
    except Exception as exc:
        return build_report(
            status="error",
            reason="generation_failed",
            message=f"No fue posible generar el audio: {exc}",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
        )

    if audio_path is None:
        cache_key = build_name_cache_key(
            normalized_name,
            voice_id,
            resolve_model_id(name_audio_config),
            resolve_version(name_audio_config),
            gender=normalized_gender,
            final_text=generated_text,
        )
        return build_report(
            status="error",
            reason="generation_returned_none",
            message=(
                "La generación devolvió None. Revisa name_audio.fallback_on_error "
                "y el log del proveedor."
            ),
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
            audio_path=cache_dir / f"{cache_key}.wav",
        )

    readability_error = ensure_audio_path_readable(audio_path)
    if readability_error is not None:
        status, reason, message = readability_error
        return build_report(
            status=status,
            reason=reason,
            message=message,
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
            audio_path=audio_path,
        )

    if cached_path is not None:
        return build_report(
            status="cache_hit",
            reason="cache_hit",
            message="Se encontró el audio en caché.",
            config=config,
            cache_dir=cache_dir,
            normalized_name=normalized_name,
            gender=normalized_gender,
            generated_text=generated_text,
            voice_id=voice_id,
            cache_hit=True,
            audio_path=audio_path,
        )

    return build_report(
        status="generated",
        reason="generated",
        message="El audio se generó correctamente.",
        config=config,
        cache_dir=cache_dir,
        normalized_name=normalized_name,
        gender=normalized_gender,
        generated_text=generated_text,
        voice_id=voice_id,
        generated=True,
        audio_path=audio_path,
    )


def build_report(
    *,
    status: str,
    reason: str,
    message: str,
    config: dict[str, object],
    cache_dir: Path,
    normalized_name: str,
    gender: str,
    generated_text: str,
    voice_id: str,
    generated: bool = False,
    cache_hit: bool = False,
    audio_path: Path | None = None,
) -> NameAudioReport:
    return NameAudioReport(
        status=status,
        reason=reason,
        message=message,
        generated=generated,
        cache_hit=cache_hit,
        gender=gender,
        generated_text=generated_text,
        playback_path=build_playback_path(audio_path, config),
        wav_path=str(audio_path) if audio_path is not None else "",
        cache_dir=str(cache_dir),
        normalized_name=normalized_name,
        voice_id=voice_id,
        mirror_paths=tuple(str(path) for path in resolve_mirror_paths(audio_path, config)),
    )


def build_strict_config(config: dict[str, object]) -> dict[str, object]:
    strict_config = copy.deepcopy(config)
    name_audio_config = strict_config.get("name_audio")
    if not isinstance(name_audio_config, dict):
        name_audio_config = {}
        strict_config["name_audio"] = name_audio_config
    name_audio_config["fallback_on_error"] = False
    return strict_config


def ensure_cache_dir(cache_dir: Path) -> tuple[str, str, str] | None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return (
            "error",
            "cache_dir_unavailable",
            f"No fue posible crear o resolver el directorio de caché {cache_dir}: {exc}",
        )

    if not os.access(cache_dir, os.W_OK):
        return (
            "error",
            "cache_dir_not_writable",
            (
                f"El directorio de caché {cache_dir} existe pero no es escribible "
                f"para el usuario actual ({os.geteuid()})."
            ),
        )
    return None


def ensure_audio_path_readable(audio_path: Path) -> tuple[str, str, str] | None:
    try:
        audio_path.chmod(0o644)
    except OSError as exc:
        return (
            "error",
            "audio_path_not_readable",
            f"No fue posible ajustar permisos de lectura sobre {audio_path}: {exc}",
        )
    return None


def resolve_mirror_paths(audio_path: Path | None, config: dict[str, object]) -> tuple[Path, ...]:
    if audio_path is None:
        return ()
    name_audio_config = get_name_audio_config(config)
    mirror_dirs = name_audio_config.get("mirror_dirs", [])
    if not isinstance(mirror_dirs, list):
        return ()

    mirror_paths: list[Path] = []
    for mirror_dir in mirror_dirs:
        mirror_path = Path(str(mirror_dir)).expanduser() / audio_path.name
        if mirror_path.exists():
            mirror_paths.append(mirror_path)
    return tuple(mirror_paths)


def get_name_audio_config(config: dict[str, object]) -> dict[str, object]:
    name_audio_config = config.get("name_audio")
    if isinstance(name_audio_config, dict):
        return name_audio_config
    return {}


def resolve_cache_dir(name_audio_config: dict[str, object]) -> Path:
    cache_dir_value = str(name_audio_config.get("cache_dir", DEFAULT_NAME_AUDIO_CACHE_DIR)).strip()
    return Path(cache_dir_value or DEFAULT_NAME_AUDIO_CACHE_DIR).expanduser().resolve()


def resolve_api_key_env(name_audio_config: dict[str, object]) -> str:
    elevenlabs_config = get_elevenlabs_config(name_audio_config)
    api_key_env = str(elevenlabs_config.get("api_key_env", DEFAULT_ELEVENLABS_API_KEY_ENV)).strip()
    return api_key_env or DEFAULT_ELEVENLABS_API_KEY_ENV


def resolve_voice_id_env(name_audio_config: dict[str, object]) -> str:
    elevenlabs_config = get_elevenlabs_config(name_audio_config)
    voice_id_env = str(
        elevenlabs_config.get("voice_id_env", DEFAULT_ELEVENLABS_VOICE_ID_ENV)
    ).strip()
    return voice_id_env or DEFAULT_ELEVENLABS_VOICE_ID_ENV


def resolve_voice_id(name_audio_config: dict[str, object]) -> str:
    voice_id_env = resolve_voice_id_env(name_audio_config)
    voice_id_from_env = os.getenv(voice_id_env, "").strip()
    if voice_id_from_env:
        return voice_id_from_env

    elevenlabs_config = get_elevenlabs_config(name_audio_config)
    return str(elevenlabs_config.get("voice_id", "")).strip()


def resolve_model_id(name_audio_config: dict[str, object]) -> str:
    elevenlabs_config = get_elevenlabs_config(name_audio_config)
    return str(elevenlabs_config.get("model_id", "")).strip()


def resolve_version(name_audio_config: dict[str, object]) -> str:
    version = str(name_audio_config.get("version", "v1")).strip()
    return version or "v1"


def get_elevenlabs_config(name_audio_config: dict[str, object]) -> dict[str, object]:
    elevenlabs_config = name_audio_config.get("elevenlabs")
    if isinstance(elevenlabs_config, dict):
        return elevenlabs_config
    return {}


def map_value_error_reason(message: str) -> str:
    if "API key" in message:
        return "missing_api_key"
    if "desactivada" in message:
        return "name_audio_disabled"
    if "voice_id" in message:
        return "missing_voice_id"
    if "model_id" in message:
        return "missing_model_id"
    if "vac" in message:
        return "empty_normalized_name"
    return "invalid_config"


def map_value_error_status(message: str) -> str:
    reason = map_value_error_reason(message)
    if reason in {"missing_api_key", "missing_voice_id", "missing_model_id"}:
        return "invalid_config"
    if reason == "name_audio_disabled":
        return "disabled"
    if reason == "empty_normalized_name":
        return "invalid_name"
    return "error"


def print_report(report: NameAudioReport) -> None:
    print(f"status={report.status}")
    print(f"reason={report.reason}")
    print(f"message={report.message}")
    print(f"generated={'true' if report.generated else 'false'}")
    print(f"cache_hit={'true' if report.cache_hit else 'false'}")
    print(f"gender={report.gender}")
    print(f"text={report.generated_text}")
    print(f"playback_path={report.playback_path}")
    print(f"wav_path={report.wav_path}")
    print(f"cache_dir={report.cache_dir}")
    print(f"normalized_name={report.normalized_name}")
    print(f"voice_id={report.voice_id}")
    print(f"mirror_paths={','.join(report.mirror_paths)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name")
    parser.add_argument("--gender", default="unknown")
    args = parser.parse_args()

    report = inspect_name_audio(args.name, load_config(), gender=args.gender)
    print_report(report)
    return 0 if report.status in {"generated", "cache_hit"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
