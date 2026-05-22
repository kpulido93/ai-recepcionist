#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vicidial_vosk_cobranza_ivr.agi_runtime import AgiSession
    from vicidial_vosk_cobranza_ivr.config import AppConfig

DEFAULT_FALLBACK_AUDIO = "custom/mensaje-cobranza"


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


def main() -> int:
    _bootstrap_src_path()
    from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError, AgiSession
    from vicidial_vosk_cobranza_ivr.config import load_app_config, resolve_runtime_paths
    from vicidial_vosk_cobranza_ivr.logging_utils import configure_logging

    fallback_logger = logging.getLogger("vicidial_vosk_cobranza_ivr.prompt")
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        fallback_logger.warning("No fue posible leer el entorno AGI: %s", exc)
        return 1

    try:
        runtime_paths = resolve_runtime_paths()
        config = load_app_config(
            runtime_paths.config_path,
            runtime_paths.intents_path,
            runtime_paths.logging_path,
        )
        logger = configure_logging(config.logging, runtime_paths.logging_path)
        _redirect_console_logging_to_stderr(logger)
    except Exception:
        fallback_logger.exception("Error cargando configuracion para prompt personalizado")
        try:
            session.set_variable("IVR_GREETING_AUDIO", DEFAULT_FALLBACK_AUDIO)
        except AgiIoError:
            return 1
        return 0

    return run_generate_personalized_prompt(
        session=session,
        config=config,
        logger=logger,
        environment=environment,
    )


def run_generate_personalized_prompt(
    *,
    session: AgiSession,
    config: AppConfig,
    logger: logging.Logger,
    environment: Mapping[str, str],
) -> int:
    from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError
    from vicidial_vosk_cobranza_ivr.prompt_builder import (
        build_cache_key,
        build_generated_audio_path,
        build_greeting_text,
        build_playback_target,
        build_template_hash,
        generate_prompt_audio,
    )

    try:
        if not config.prompts.personalized_greeting_enabled:
            session.set_variable("IVR_GREETING_AUDIO", DEFAULT_FALLBACK_AUDIO)
            return 0

        lead_id = _read_channel_variable(session, environment, "IVR_LEAD_ID")
        client_name = _read_channel_variable(session, environment, "IVR_CLIENT_NAME")
        bank_name = _read_channel_variable(session, environment, "IVR_BANK_NAME")

        greeting_text = build_greeting_text(client_name, bank_name, config.prompts)
        template_hash = build_template_hash(config.prompts)
        cache_key = build_cache_key(lead_id, client_name, bank_name, template_hash)
        output_path = build_generated_audio_path(cache_key, config.prompts)
        playback_target = build_playback_target(cache_key, config.prompts)

        if not (config.prompts.cache_enabled and output_path.exists()):
            generate_prompt_audio(greeting_text, output_path, config.prompts)

        session.set_variable("IVR_GREETING_AUDIO", playback_target)
        _maybe_log_prompt_text(logger, config, greeting_text)
        logger.info("Prompt personalizado listo para Playback.")
        return 0
    except AgiIoError as exc:
        logger.warning("No fue posible setear IVR_GREETING_AUDIO: %s", exc)
        return 1
    except Exception as exc:
        logger.warning("Fallo prompt personalizado, usando fallback estatico: %s", exc)
        try:
            session.set_variable("IVR_GREETING_AUDIO", DEFAULT_FALLBACK_AUDIO)
        except AgiIoError as fallback_exc:
            logger.warning("No fue posible setear fallback IVR_GREETING_AUDIO: %s", fallback_exc)
            return 1
        return 0


def _read_channel_variable(
    session: AgiSession,
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    direct_value = environment.get(name)
    if direct_value is not None:
        stripped = direct_value.strip()
        return stripped or None

    session_getter = getattr(session, "get_variable", None)
    if callable(session_getter):
        value = session_getter(name)
        if value is None:
            return None
        stripped_value = str(value).strip()
        return stripped_value or None

    return None


def _maybe_log_prompt_text(
    logger: logging.Logger,
    config: AppConfig,
    greeting_text: str,
) -> None:
    if not config.prompts.debug_log_values:
        return
    if config.prompts.privacy_mode or config.logging.mask_phone_numbers:
        return
    logger.debug("Prompt personalizado generado texto=%s", greeting_text)


def _redirect_console_logging_to_stderr(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
