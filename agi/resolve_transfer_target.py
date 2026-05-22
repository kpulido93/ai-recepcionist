#!/usr/bin/env python3
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


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
        "IVR_ROUTING_CONFIG",
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
from vicidial_vosk_cobranza_ivr.routing import (  # noqa: E402
    SAFE_DEFAULT_TRANSFER_TARGET,
    load_routing_config,
    resolve_transfer_target,
)

LOGGER = logging.getLogger("vicidial_vosk_cobranza_ivr.resolve_transfer_target")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        LOGGER.warning("No fue posible leer el entorno AGI para ruteo de transferencia: %s", exc)
        return 1

    return run_resolve_transfer_target(session=session, environment=environment)


def run_resolve_transfer_target(session: AgiSession, environment: dict[str, str]) -> int:
    fallback_target = SAFE_DEFAULT_TRANSFER_TARGET
    try:
        routing_config = load_routing_config(resolve_routing_config_path())
        fallback_target = resolve_transfer_target(config=routing_config)
        transfer_target = resolve_transfer_target(
            portfolio_id=_read_agi_or_env_value(session, environment, "IVR_PORTFOLIO_ID"),
            bank_name=_read_agi_or_env_value(session, environment, "IVR_BANK_NAME"),
            config=routing_config,
        )
    except Exception as exc:
        LOGGER.warning(
            "No fue posible resolver transferencia por cartera; se usara fallback: %s", exc
        )
        transfer_target = fallback_target

    try:
        session.set_variable("IVR_TRANSFER_TARGET", transfer_target)
    except AgiIoError as exc:
        LOGGER.warning("No fue posible setear IVR_TRANSFER_TARGET: %s", exc)
        return 1

    return 0


def resolve_routing_config_path() -> Path:
    env_value = os.getenv("IVR_ROUTING_CONFIG")
    if env_value:
        return Path(env_value).expanduser().resolve()

    config_env_value = os.getenv("VOSK_COBRANZA_CONFIG")
    if config_env_value:
        config_path = Path(config_env_value).expanduser().resolve()
        return (config_path.parent / "routing.yml").resolve()

    return (PROJECT_ROOT / "config" / "routing.yml").resolve()


def _read_agi_or_env_value(
    session: AgiSession,
    environment: dict[str, str],
    variable_name: str,
) -> str | None:
    environment_value = _sanitize_agi_value(environment.get(variable_name.lower()))
    if environment_value:
        return environment_value

    env_value = _sanitize_agi_value(os.getenv(variable_name))
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
    return _sanitize_agi_value(value) or None


def _sanitize_agi_value(value: str | None) -> str | None:
    if value is None:
        return None
    compact_value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    if not compact_value:
        return None
    return compact_value


if __name__ == "__main__":
    raise SystemExit(main())
