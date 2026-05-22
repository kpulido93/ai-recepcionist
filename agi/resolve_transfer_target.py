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
    from vicidial_vosk_cobranza_ivr.routing import RoutingConfig

DEFAULT_FALLBACK_TRANSFER_TARGET = "PJSIP/1002"


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
        "VOSK_COBRANZA_ROUTING",
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
    from vicidial_vosk_cobranza_ivr.routing import load_routing_config, resolve_routing_config_path

    fallback_logger = logging.getLogger("vicidial_vosk_cobranza_ivr.routing")
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
        routing_config = load_routing_config(resolve_routing_config_path())
    except Exception:
        fallback_logger.exception("Error cargando configuracion de routing")
        try:
            session.set_variable("IVR_TRANSFER_TARGET", DEFAULT_FALLBACK_TRANSFER_TARGET)
        except AgiIoError:
            return 1
        return 0

    return run_resolve_transfer_target(
        session=session,
        config=config,
        logger=logger,
        environment=environment,
        routing_config=routing_config,
    )


def run_resolve_transfer_target(
    *,
    session: AgiSession,
    config: AppConfig,
    logger: logging.Logger,
    environment: Mapping[str, str],
    routing_config: RoutingConfig,
) -> int:
    from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError
    from vicidial_vosk_cobranza_ivr.routing import resolve_transfer_target

    try:
        bank_name = _read_channel_variable(session, environment, "IVR_BANK_NAME")
        portfolio_id = _read_channel_variable(session, environment, "IVR_PORTFOLIO_ID")

        transfer_target = resolve_transfer_target(
            bank_name=bank_name,
            portfolio_id=portfolio_id,
            config=routing_config,
        )
        session.set_variable("IVR_TRANSFER_TARGET", transfer_target)
        logger.info("Target de transferencia resuelto.")
        return 0
    except AgiIoError as exc:
        logger.warning("No fue posible setear IVR_TRANSFER_TARGET: %s", exc)
        return 1
    except Exception as exc:
        logger.warning("Fallo resolviendo transfer_target, usando fallback: %s", exc)
        try:
            session.set_variable("IVR_TRANSFER_TARGET", DEFAULT_FALLBACK_TRANSFER_TARGET)
        except AgiIoError as fallback_exc:
            logger.warning("No fue posible setear fallback IVR_TRANSFER_TARGET: %s", fallback_exc)
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


def _redirect_console_logging_to_stderr(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
