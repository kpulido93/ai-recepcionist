from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError, AgiSession
from vicidial_vosk_cobranza_ivr.audio import capture_eagi_audio
from vicidial_vosk_cobranza_ivr.config import AppConfig, load_app_config, resolve_runtime_paths
from vicidial_vosk_cobranza_ivr.intent_classifier import IntentClassifier
from vicidial_vosk_cobranza_ivr.logging_utils import (
    configure_logging,
    contains_sensitive_data,
)
from vicidial_vosk_cobranza_ivr.service import CobranzaIvrService
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient

SAFE_AGI_VALUE_LENGTH = 2048


def build_service(
    config: AppConfig,
    logger: logging.Logger,
) -> CobranzaIvrService:
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
    )
    vosk_client = VoskClient(
        websocket_url=config.vosk.websocket_url,
        timeout_seconds=config.vosk.websocket_timeout_seconds,
    )
    return CobranzaIvrService(
        config=config,
        classifier=classifier,
        vosk_client=vosk_client,
        logger=logger,
    )


def run_eagi() -> int:
    fallback_logger = logging.getLogger("vicidial_vosk_cobranza_ivr")
    session = AgiSession()

    try:
        environment = session.read_environment()
    except AgiIoError as exc:
        fallback_logger.warning("No fue posible leer el entorno AGI: %s", exc)
        return 1

    try:
        runtime_paths = resolve_runtime_paths()
        config = load_app_config(runtime_paths.config_path, runtime_paths.intents_path)
        logger = configure_logging(config.logging, runtime_paths.logging_path)
        _redirect_console_logging_to_stderr(logger)
        service = build_service(config=config, logger=logger)
    except Exception:
        fallback_logger.exception("Error cargando configuracion EAGI")
        _safe_write_error_result(session)
        return 1

    return run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        environment=environment,
    )


def run_eagi_session(
    session: AgiSession,
    service: CobranzaIvrService,
    config: AppConfig,
    logger: logging.Logger,
    capture_audio: Callable[[int, int, int], bytes] = capture_eagi_audio,
    environment: dict[str, str] | None = None,
) -> int:
    try:
        call_environment = environment if environment is not None else session.read_environment()
    except AgiIoError as exc:
        logger.warning("No fue posible leer el entorno AGI activo: %s", exc)
        return 1

    caller = call_environment.get("agi_callerid", "")
    channel = call_environment.get("agi_channel", "")
    uniqueid = call_environment.get("agi_uniqueid", "")
    dtmf = (call_environment.get("agi_arg_1", "") or "").strip() or None
    logger.info("Inicio EAGI uniqueid=%s channel=%s caller=%s", uniqueid, channel, caller)

    try:
        if dtmf and dtmf in config.ivr.dtmf_map:
            outcome = service.classify_audio_bytes(b"", config.vosk.sample_rate, dtmf=dtmf)
        else:
            audio_bytes = capture_audio(3, config.ivr.listen_seconds, config.vosk.sample_rate)
            outcome = service.classify_audio_bytes(
                audio_bytes=audio_bytes,
                sample_rate=config.vosk.sample_rate,
            )

        transcript = sanitize_channel_value(outcome.transcript)
        write_ok = _write_agi_result(
            session=session,
            channel_variable_name=config.asterisk.channel_variable_name,
            intent=outcome.intent.value,
            text=transcript,
            confidence=f"{outcome.confidence:.2f}",
            source=outcome.source,
        )
        _log_result(
            session=session,
            logger=logger,
            config=config,
            intent=outcome.intent.value,
            source=outcome.source,
            confidence=outcome.confidence,
            transcript=transcript,
            matched_phrase=outcome.matched_value,
            uniqueid=uniqueid,
            channel=channel,
            caller=caller,
        )
        if not write_ok:
            logger.warning("Asterisk no confirmo SET VARIABLE para todas las variables VOSK.")
            return 1
        return 1 if outcome.source == "error" else 0
    except AgiIoError as exc:
        logger.warning("Canal AGI no disponible para devolver resultado: %s", exc)
        return 1
    except Exception:
        logger.exception("Error durante la ejecucion EAGI")
        _safe_write_error_result(
            session,
            config.asterisk.channel_variable_name,
            config.ivr.default_intent,
        )
        return 1


def sanitize_channel_value(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:SAFE_AGI_VALUE_LENGTH]


def agi_set_variable(session: AgiSession, name: str, value: str) -> str:
    return session.set_variable(name, value)


def _write_agi_result(
    session: AgiSession,
    channel_variable_name: str,
    intent: str,
    text: str,
    confidence: str,
    source: str,
) -> bool:
    responses = [
        agi_set_variable(session, "VOSK_TEXT", text),
        agi_set_variable(session, "VOSK_INTENT", intent),
        agi_set_variable(session, "VOSK_CONFIDENCE", confidence),
        agi_set_variable(session, "VOSK_SOURCE", source),
    ]
    if channel_variable_name != "VOSK_INTENT":
        responses.append(agi_set_variable(session, channel_variable_name, intent))

    return all(response.startswith("200 result=1") for response in responses)


def _log_result(
    session: AgiSession,
    logger: logging.Logger,
    config: AppConfig,
    intent: str,
    source: str,
    confidence: float,
    transcript: str,
    matched_phrase: str | None,
    uniqueid: str,
    channel: str,
    caller: str,
) -> None:
    matched_phrase_fragment = _format_matched_phrase(matched_phrase)
    if config.logging.log_transcript and transcript:
        verbose_message = (
            f"VOSK intent={intent} source={source} "
            f"confidence={confidence:.2f} transcript={transcript}"
        )
        _safe_verbose(session, logger, verbose_message, 1)
        logger.info(
            "Intent=%s source=%s confidence=%.2f transcript=%s uniqueid=%s channel=%s caller=%s%s",
            intent,
            source,
            confidence,
            transcript,
            uniqueid,
            channel,
            caller,
            matched_phrase_fragment,
        )
        return

    _safe_verbose(
        session,
        logger,
        f"VOSK intent={intent} source={source} confidence={confidence:.2f}",
        1,
    )
    logger.info(
        "Intent=%s source=%s confidence=%.2f uniqueid=%s channel=%s caller=%s%s",
        intent,
        source,
        confidence,
        uniqueid,
        channel,
        caller,
        matched_phrase_fragment,
    )


def _redirect_console_logging_to_stderr(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(sys.stderr)


def _format_matched_phrase(matched_phrase: str | None) -> str:
    if not matched_phrase:
        return ""
    if contains_sensitive_data(matched_phrase):
        return ""
    return f" matched_phrase={matched_phrase}"


def _safe_verbose(
    session: AgiSession,
    logger: logging.Logger,
    message: str,
    level: int,
) -> None:
    try:
        session.verbose(message, level)
    except AgiIoError as exc:
        logger.warning("No fue posible escribir VERBOSE AGI: %s", exc)


def _safe_write_error_result(
    session: AgiSession,
    channel_variable_name: str = "VOSK_INTENT",
    default_intent: str = "DUDA",
) -> None:
    try:
        _write_agi_result(
            session=session,
            channel_variable_name=channel_variable_name,
            intent=default_intent,
            text="",
            confidence="0.00",
            source="error",
        )
    except AgiIoError:
        return
