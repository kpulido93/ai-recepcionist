#!/usr/bin/env python3
from __future__ import annotations

import hashlib
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
from vicidial_vosk_cobranza_ivr.prompt_builder import (  # noqa: E402
    build_bank_greeting_audio,
    build_cache_key,
    build_greeting_text,
    generate_prompt_audio,
    get_default_greeting_audio,
    get_greeting_followup_audio,
    sanitize_prompt_value,
)

LOGGER = logging.getLogger("vicidial_vosk_cobranza_ivr.prompt_builder")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        LOGGER.warning("No fue posible leer el entorno AGI para saludo personalizado: %s", exc)
        return 1

    return run_generate_personalized_prompt(session=session, environment=environment)


def run_generate_personalized_prompt(session: AgiSession, environment: dict[str, str]) -> int:
    config = load_prompt_config()
    prompts_config = _get_prompts_config(config)
    bank_name = _read_agi_or_env_value(session, environment, "IVR_BANK_NAME")
    bank_greeting_audio = build_bank_greeting_audio(bank_name, config)

    try:
        greeting_audio = _resolve_or_generate_greeting_audio(
            lead_id=_read_agi_or_env_value(session, environment, "IVR_LEAD_ID"),
            client_name=_read_agi_or_env_value(session, environment, "IVR_CLIENT_NAME"),
            bank_name=bank_name,
            config=config,
            prompts_config=prompts_config,
        )
    except Exception as exc:
        LOGGER.warning("No fue posible generar saludo personalizado; se usará fallback: %s", exc)
        greeting_audio = get_default_greeting_audio(config)

    greeting_followup_audio = ""
    if greeting_audio == get_default_greeting_audio(config):
        greeting_followup_audio = get_greeting_followup_audio(config)

    try:
        session.set_variable("IVR_GREETING_AUDIO", greeting_audio)
        session.set_variable("IVR_GREETING_FOLLOWUP_AUDIO", greeting_followup_audio)
        session.set_variable("IVR_BANK_GREETING_AUDIO", bank_greeting_audio)
    except AgiIoError as exc:
        LOGGER.warning("No fue posible setear variables AGI de saludo: %s", exc)
        return 1

    return 0


def load_prompt_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    try:
        with config_path.expanduser().resolve().open("r", encoding="utf-8") as file_handler:
            config_data = yaml.safe_load(file_handler) or {}
    except OSError as exc:
        LOGGER.warning("No fue posible leer configuración de prompts: %s", exc)
        return {}

    if not isinstance(config_data, dict):
        return {}
    return config_data


def _resolve_or_generate_greeting_audio(
    *,
    lead_id: str | None,
    client_name: str | None,
    bank_name: str | None,
    config: dict[str, object],
    prompts_config: dict[str, object],
) -> str:
    if not bool(prompts_config.get("personalized_greeting_enabled", False)):
        return get_default_greeting_audio(config)

    generated_audio_dir = Path(
        str(prompts_config.get("generated_audio_dir", "/var/lib/asterisk/sounds/custom/generated"))
    )
    generated_audio_dir = generated_audio_dir.expanduser().resolve()
    playback_prefix = str(prompts_config.get("generated_audio_playback_prefix", "custom/generated"))
    playback_prefix = playback_prefix.strip("/")

    greeting_text = build_greeting_text(client_name, bank_name, config)
    template_hash = _build_template_hash(prompts_config)
    cache_key = build_cache_key(lead_id, client_name, bank_name, template_hash)
    output_path = _safe_output_path(generated_audio_dir, f"{cache_key}.wav")

    if not bool(prompts_config.get("cache_enabled", True)) or not output_path.exists():
        generate_prompt_audio(greeting_text, output_path, config)
        LOGGER.info("Saludo personalizado generado.")
    else:
        LOGGER.info("Saludo personalizado cargado desde cache.")

    LOGGER.debug(
        "Saludo personalizado listo path=%s playback=%s/%s",
        output_path,
        playback_prefix,
        cache_key,
    )
    return f"{playback_prefix}/{cache_key}"


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


def _get_prompts_config(config: dict[str, object]) -> dict[str, object]:
    prompts_config = config.get("prompts")
    if isinstance(prompts_config, dict):
        return prompts_config
    return {}


def _build_template_hash(prompts_config: dict[str, object]) -> str:
    template_parts = [
        str(prompts_config.get("greeting_template", "")),
        str(prompts_config.get("greeting_template_without_name", "")),
        str(prompts_config.get("greeting_fallback", "")),
    ]
    return hashlib.sha256("|".join(template_parts).encode("utf-8")).hexdigest()[:16]


def _safe_output_path(base_dir: Path, filename: str) -> Path:
    output_path = (base_dir / filename).resolve()
    try:
        output_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("La ruta de audio generado queda fuera del directorio permitido.") from exc
    return output_path


if __name__ == "__main__":
    raise SystemExit(main())
