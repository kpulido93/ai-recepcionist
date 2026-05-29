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
        "IVR_LEAD_CONTEXT_CSV",
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
from vicidial_vosk_cobranza_ivr.lead_context import (  # noqa: E402
    LeadContext,
    load_lead_context_from_csv,
    sanitize_lead_value,
)

LOGGER = logging.getLogger("vicidial_vosk_cobranza_ivr.lead_context")
LEAD_CONTEXT_VARIABLES = {
    "IVR_CLIENT_NAME": "client_name",
    "IVR_CLIENT_GENDER": "client_gender",
    "IVR_BANK_NAME": "bank_name",
    "IVR_PORTFOLIO_ID": "portfolio_id",
    "IVR_CAMPAIGN_ID": "campaign_id",
    "IVR_LIST_ID": "list_id",
}


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        LOGGER.warning("No fue posible leer el entorno AGI para contexto de lead: %s", exc)
        return 1

    return run_load_lead_context(session=session, environment=environment)


def run_load_lead_context(session: AgiSession, environment: dict[str, str]) -> int:
    lead_id = _read_agi_or_env_value(session, environment, "IVR_LEAD_ID")
    phone_number = _read_agi_or_env_value(session, environment, "IVR_PHONE_NUMBER")
    if not phone_number:
        phone_number = _read_agi_or_env_value(session, environment, "CALLERID(num)")
    if not phone_number:
        phone_number = sanitize_lead_value(environment.get("agi_callerid"))

    context: LeadContext | None = None
    csv_path = resolve_lead_context_csv_path()
    if csv_path is not None:
        try:
            context = load_lead_context_from_csv(
                csv_path,
                lead_id=lead_id,
                phone_number=phone_number,
            )
        except OSError as exc:
            LOGGER.warning("No fue posible leer CSV de contexto de lead: %s", exc)

    if context is None:
        context = LeadContext(
            lead_id=None,
            phone_number=None,
            client_name=None,
            client_gender=None,
            bank_name=None,
            portfolio_id=None,
            campaign_id=None,
            list_id=None,
        )
        LOGGER.info("Contexto de lead no encontrado; se continuara sin datos personalizados.")
    else:
        LOGGER.info("Contexto de lead cargado.")
        LOGGER.debug(
            "Contexto de lead debug lead_id=%s phone=%s client=%s bank=%s portfolio=%s",
            context.lead_id,
            context.phone_number,
            context.client_name,
            context.bank_name,
            context.portfolio_id,
        )

    return _write_context_variables(session, context)


def resolve_lead_context_csv_path() -> Path | None:
    env_value = os.getenv("IVR_LEAD_CONTEXT_CSV")
    if env_value:
        return Path(env_value).expanduser().resolve()

    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    config_path = config_path.expanduser().resolve()
    configured_path = _read_csv_path_from_config(config_path)
    if configured_path is None:
        return PROJECT_ROOT / "config" / "lead_context.sample.csv"
    if configured_path.is_absolute():
        return configured_path
    return (config_path.parent / configured_path).resolve()


def _read_csv_path_from_config(config_path: Path) -> Path | None:
    try:
        with config_path.open("r", encoding="utf-8") as file_handler:
            config_data = yaml.safe_load(file_handler) or {}
    except OSError as exc:
        LOGGER.warning("No fue posible leer configuracion IVR para contexto de lead: %s", exc)
        return None

    if not isinstance(config_data, dict):
        return None

    lead_context_config = config_data.get("lead_context", {})
    if not isinstance(lead_context_config, dict):
        return None

    csv_path = lead_context_config.get("csv_path")
    if not csv_path:
        return None
    return Path(str(csv_path)).expanduser()


def _read_agi_or_env_value(
    session: AgiSession,
    environment: dict[str, str],
    variable_name: str,
) -> str | None:
    value = sanitize_lead_value(environment.get(variable_name.lower()))
    if value:
        return value

    env_value = sanitize_lead_value(os.getenv(variable_name))
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
    return sanitize_lead_value(value)


def _write_context_variables(session: AgiSession, context: LeadContext) -> int:
    try:
        for variable_name, attr_name in LEAD_CONTEXT_VARIABLES.items():
            value = getattr(context, attr_name)
            session.set_variable(variable_name, value or "")
    except AgiIoError as exc:
        LOGGER.warning("No fue posible setear variables AGI de contexto de lead: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
