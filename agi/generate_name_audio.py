#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import yaml


def _bootstrap_src_path() -> None:
    for candidate in _candidate_src_roots():
        if str(candidate) in sys.path:
            return
        if candidate.exists():
            sys.path.insert(0, str(candidate))
            return


def _candidate_src_roots() -> list[Path]:
    candidates: list[Path] = []

    for env_name in (
        "VOSK_COBRANZA_CONFIG",
        "VOSK_COBRANZA_INTENTS",
        "VOSK_COBRANZA_LOGGING",
    ):
        env_value = os.getenv(env_name)
        if not env_value:
            continue
        resolved = Path(env_value).expanduser().resolve()
        project_root = resolved.parents[1] if len(resolved.parents) > 1 else resolved.parent
        candidates.append(project_root / "src")

    script_path = Path(__file__).resolve()
    if len(script_path.parents) > 1:
        candidates.append(script_path.parents[1] / "src")

    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique_candidates.append(candidate)

    return unique_candidates


_bootstrap_src_path()

from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError, AgiSession  # noqa: E402
from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT  # noqa: E402
from vicidial_vosk_cobranza_ivr.name_audio_cache import get_or_generate_name_audio  # noqa: E402
from vicidial_vosk_cobranza_ivr.prompt_builder import sanitize_prompt_value  # noqa: E402

LOGGER = logging.getLogger("vicidial_vosk_cobranza_ivr.generate_name_audio")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        LOGGER.warning("No fue posible leer el entorno AGI para audio de nombre: %s", exc)
        return 1

    return run_generate_name_audio(session=session, environment=environment)


def run_generate_name_audio(session: AgiSession, environment: dict[str, str]) -> int:
    config = load_name_audio_config()
    name_audio_value = ""
    client_name = _read_agi_or_env_value(session, environment, "IVR_CLIENT_NAME")

    if client_name:
        try:
            audio_path = get_or_generate_name_audio(client_name, config)
            if audio_path is not None:
                name_audio_value = _build_playback_path(audio_path, config)
        except Exception as exc:
            LOGGER.warning("No fue posible resolver audio de nombre; se usará fallback: %s", exc)

    try:
        session.set_variable("IVR_NAME_AUDIO", name_audio_value)
    except AgiIoError as exc:
        LOGGER.warning("No fue posible setear IVR_NAME_AUDIO: %s", exc)
        return 1

    return 0


def load_name_audio_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    try:
        with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
            config_data = yaml.safe_load(file_handler) or {}
    except OSError as exc:
        LOGGER.warning("No fue posible leer configuración de audio de nombre: %s", exc)
        return {}

    if not isinstance(config_data, dict):
        return {}
    return config_data


def _build_playback_path(audio_path: Path, config: dict[str, object]) -> str:
    name_audio_config = config.get("name_audio", {})
    if not isinstance(name_audio_config, dict):
        name_audio_config = {}
    playback_prefix = str(name_audio_config.get("playback_prefix", "custom/generated/names"))
    playback_prefix = playback_prefix.strip("/")
    return f"{playback_prefix}/{audio_path.stem}"


def _read_agi_or_env_value(
    session: AgiSession,
    environment: dict[str, str],
    variable_name: str,
) -> str | None:
    value = sanitize_prompt_value(environment.get(variable_name.lower()))
    if value:
        return value

    env_value = sanitize_prompt_value(os.getenv(variable_name))
    if env_value:
        return env_value

    try:
        response = session.command(f"GET VARIABLE {variable_name}")
    except AgiIoError as exc:
        LOGGER.debug("No fue posible consultar variable AGI %s: %s", variable_name, exc)
        return None

    return _parse_get_variable_response(response)


def _parse_get_variable_response(response: str) -> str | None:
    if "result=0" in response:
        return None
    if "(" not in response or ")" not in response:
        return None
    value = response.rsplit("(", 1)[1].rsplit(")", 1)[0]
    return sanitize_prompt_value(value) or None


if __name__ == "__main__":
    raise SystemExit(main())
