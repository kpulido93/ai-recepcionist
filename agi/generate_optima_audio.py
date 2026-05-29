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
from vicidial_vosk_cobranza_ivr.lead_context import sanitize_lead_value  # noqa: E402
from vicidial_vosk_cobranza_ivr.optima_9913_lab_audio import (  # noqa: E402
    OPTIMA_9913_DEUDA_BANCO,
    OPTIMA_9913_PREGUNTA_ABOGADO,
    OPTIMA_9913_SALUDO,
    build_optima_9913_lab_playback_path,
    get_or_generate_optima_9913_lab_audio,
)
from vicidial_vosk_cobranza_ivr.optima_audio_cache import (  # noqa: E402
    OPTIMA_DEUDA_BANCO,
    OPTIMA_SALUDO_NOMBRE,
    build_optima_playback_path,
    get_optima_fallback_audio,
    get_or_generate_optima_audio,
)

LOGGER = logging.getLogger("vicidial_vosk_cobranza_ivr.generate_optima_audio")


def main() -> int:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), stream=sys.stderr)
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        LOGGER.warning("No fue posible leer el entorno AGI para audio Optima: %s", exc)
        return 1

    return run_generate_optima_audio(session=session, environment=environment)


def run_generate_optima_audio(session: AgiSession, environment: dict[str, str]) -> int:
    config = load_optima_audio_config()
    saludo_audio_value = get_optima_fallback_audio(OPTIMA_SALUDO_NOMBRE, config)
    pregunta_audio_value = "custom/optima-02-pregunta-abogado"
    deuda_audio_value = get_optima_fallback_audio(OPTIMA_DEUDA_BANCO, config)
    lead_id = _read_agi_or_env_value(session, environment, "IVR_LEAD_ID", max_len=80)
    client_name = _read_agi_or_env_value(session, environment, "IVR_CLIENT_NAME", max_len=120)
    if not client_name:
        client_name = _read_agi_or_env_value(session, environment, "IVR_PERSON_NAME", max_len=120)
    bank_name = _read_agi_or_env_value(session, environment, "IVR_BANK_NAME", max_len=160)

    if lead_id and lead_id.startswith("lab-"):
        saludo_audio_value, pregunta_audio_value, deuda_audio_value = _resolve_lab_prompt_audio(
            config=config,
            lead_id=lead_id,
            client_name=client_name,
            bank_name=bank_name,
        )
    else:
        saludo_audio_value, deuda_audio_value = _resolve_segmented_prompt_audio(
            config=config,
            client_name=client_name,
            bank_name=bank_name,
            saludo_audio_value=saludo_audio_value,
            deuda_audio_value=deuda_audio_value,
        )

    try:
        session.set_variable("IVR_OPTIMA_SALUDO_NOMBRE_AUDIO", saludo_audio_value)
        session.set_variable("IVR_OPTIMA_PREGUNTA_ABOGADO_AUDIO", pregunta_audio_value)
        session.set_variable("IVR_OPTIMA_DEUDA_BANCO_AUDIO", deuda_audio_value)
    except AgiIoError as exc:
        LOGGER.warning("No fue posible setear variables AGI de audio Optima: %s", exc)
        return 1

    return 0


def _resolve_segmented_prompt_audio(
    *,
    config: dict[str, object],
    client_name: str | None,
    bank_name: str | None,
    saludo_audio_value: str,
    deuda_audio_value: str,
) -> tuple[str, str]:
    if client_name:
        try:
            saludo_audio_path = get_or_generate_optima_audio(
                OPTIMA_SALUDO_NOMBRE,
                client_name,
                config,
            )
            if saludo_audio_path is not None:
                saludo_audio_value = build_optima_playback_path(saludo_audio_path, config)
        except Exception as exc:
            LOGGER.warning(
                "No fue posible resolver audio Optima de saludo; se usará fallback estático: %s",
                exc,
            )

    if bank_name:
        try:
            deuda_audio_path = get_or_generate_optima_audio(
                OPTIMA_DEUDA_BANCO,
                bank_name,
                config,
            )
            if deuda_audio_path is not None:
                deuda_audio_value = build_optima_playback_path(deuda_audio_path, config)
        except Exception as exc:
            LOGGER.warning(
                "No fue posible resolver audio Optima de deuda; se usará fallback estático: %s",
                exc,
            )

    return saludo_audio_value, deuda_audio_value


def _resolve_lab_prompt_audio(
    *,
    config: dict[str, object],
    lead_id: str,
    client_name: str | None,
    bank_name: str | None,
) -> tuple[str, str, str]:
    saludo_audio_value = ""
    pregunta_audio_value = "custom/optima-02-pregunta-abogado"
    deuda_audio_value = "custom/optima-03-deuda-banco"
    if not client_name or not bank_name:
        return saludo_audio_value, pregunta_audio_value, deuda_audio_value

    for prompt_kind, variable_name in (
        (OPTIMA_9913_SALUDO, "saludo"),
        (OPTIMA_9913_PREGUNTA_ABOGADO, "pregunta"),
        (OPTIMA_9913_DEUDA_BANCO, "deuda"),
    ):
        try:
            audio_path = get_or_generate_optima_9913_lab_audio(
                prompt_kind,
                lead_id=lead_id,
                person_name=client_name,
                bank_name=bank_name,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                (
                    "No fue posible resolver audio 9913 de %s para laboratorio; "
                    "se usará fallback estático: %s"
                ),
                variable_name,
                exc,
            )
            audio_path = None

        if audio_path is None:
            continue
        playback_path = build_optima_9913_lab_playback_path(lead_id, prompt_kind)
        if prompt_kind == OPTIMA_9913_SALUDO:
            saludo_audio_value = playback_path
        elif prompt_kind == OPTIMA_9913_PREGUNTA_ABOGADO:
            pregunta_audio_value = playback_path
        else:
            deuda_audio_value = playback_path

    return saludo_audio_value, pregunta_audio_value, deuda_audio_value


def load_optima_audio_config() -> dict[str, object]:
    config_path = Path(os.getenv("VOSK_COBRANZA_CONFIG", PROJECT_ROOT / "config" / "ivr.yml"))
    try:
        resolved_config_path = config_path.expanduser().resolve()
        with resolved_config_path.open("r", encoding="utf-8") as file_handler:
            config_data = yaml.safe_load(file_handler) or {}
    except OSError as exc:
        LOGGER.warning("No fue posible leer configuración de audio Optima: %s", exc)
        return {}

    if not isinstance(config_data, dict):
        return {}
    config_data["__config_path__"] = str(resolved_config_path)
    return config_data


def _read_agi_or_env_value(
    session: AgiSession,
    environment: dict[str, str],
    variable_name: str,
    *,
    max_len: int,
) -> str | None:
    raw_value = environment.get(variable_name.lower())
    sanitized_value = sanitize_lead_value(raw_value, max_len=max_len)
    if sanitized_value:
        return sanitized_value

    env_value = sanitize_lead_value(os.getenv(variable_name), max_len=max_len)
    if env_value:
        return env_value

    try:
        response = session.command(f"GET VARIABLE {variable_name}")
    except AgiIoError as exc:
        LOGGER.debug("No fue posible consultar variable AGI %s: %s", variable_name, exc)
        return None

    return _parse_get_variable_response(response, max_len=max_len)


def _parse_get_variable_response(response: str, *, max_len: int) -> str | None:
    if "result=0" in response:
        return None
    if "(" not in response or ")" not in response:
        return None
    value = response.rsplit("(", 1)[1].rsplit(")", 1)[0]
    return sanitize_lead_value(value, max_len=max_len)


if __name__ == "__main__":
    raise SystemExit(main())
