from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError, AgiSession
from vicidial_vosk_cobranza_ivr.audio import (
    CaptureResult,
    calculate_rms,
    capture_eagi_audio_result,
)
from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    load_app_config,
    resolve_runtime_paths,
)
from vicidial_vosk_cobranza_ivr.intent_classifier import (
    IntentClassifier,
    detect_early_intent,
    intent_value,
)
from vicidial_vosk_cobranza_ivr.logging_utils import (
    configure_logging,
    mask_sensitive_data,
)
from vicidial_vosk_cobranza_ivr.logging_utils import (
    mask_phone_numbers as mask_sensitive_phone_numbers,
)
from vicidial_vosk_cobranza_ivr.service import CobranzaIvrService
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient

SAFE_AGI_VALUE_LENGTH = 2048
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")


def build_service(
    config: AppConfig,
    logger: logging.Logger,
    audio_sender: Callable[[object, bytes], None] | None = None,
) -> CobranzaIvrService:
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
    )
    vosk_client = VoskClient(
        websocket_url=config.vosk.websocket_url,
        timeout_seconds=config.vosk.websocket_timeout_seconds,
        audio_sender=audio_sender,
        early_detection_enabled=config.ivr.early_detection_enabled,
        early_detection_min_audio_ms=config.ivr.early_detection_min_audio_ms,
        early_detection_min_chars=config.ivr.early_detection_min_chars,
        early_intent_detector=lambda partial: detect_early_intent(
            partial,
            intents_config=config.intents,
            supported_intents=config.intents.keys(),
        ),
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
    capture_audio: Callable[[int, int, int], bytes | CaptureResult] | None = None,
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
    masked_channel = _mask_log_value(channel, config.logging.mask_phone_numbers)
    masked_caller = _mask_log_value(caller, config.logging.mask_phone_numbers)
    logger.info(
        "Inicio EAGI uniqueid=%s channel=%s caller=%s",
        uniqueid,
        masked_channel,
        masked_caller,
    )

    try:
        capture_result: CaptureResult | None = None
        if dtmf and dtmf in config.ivr.dtmf_map:
            outcome = service.classify_audio_bytes(b"", config.ivr.sample_rate, dtmf=dtmf)
            capture_finish_reason = "dtmf"
        else:
            capture_result = _capture_audio_result(
                capture_audio=capture_audio,
                config=config,
            )
            logger.debug(
                (
                    "EAGI capture bytes_read=%s duration_ms=%s speech_started=%s "
                    "silence_ms=%s rms_avg=%.2f rms_max=%.2f stop_reason=%s"
                ),
                capture_result.bytes_read,
                capture_result.duration_ms,
                capture_result.speech_started,
                capture_result.silence_ms,
                capture_result.average_rms,
                capture_result.max_rms,
                capture_result.finish_reason,
            )
            _maybe_dump_audio_bytes(
                audio_bytes=capture_result.audio_bytes,
                config=config,
                logger=logger,
                uniqueid=uniqueid,
                caller=caller,
            )
            outcome = service.classify_audio_bytes(
                audio_bytes=capture_result.audio_bytes,
                sample_rate=config.ivr.sample_rate,
            )
            capture_finish_reason = capture_result.finish_reason

        transcript = sanitize_channel_value(outcome.transcript)
        finish_reason = _resolve_finish_reason(capture_finish_reason, outcome.finish_reason)
        _log_vosk_debug(logger=logger, config=config, raw_messages=outcome.raw_messages)
        write_ok = _write_agi_result(
            session=session,
            channel_variable_name=config.asterisk.channel_variable_name,
            intent=intent_value(outcome.intent),
            text=transcript,
            confidence=f"{outcome.confidence:.2f}",
            source=outcome.source,
        )
        _log_result(
            session=session,
            logger=logger,
            config=config,
            intent=intent_value(outcome.intent),
            source=outcome.source,
            confidence=outcome.confidence,
            transcript=transcript,
            matched_phrase=outcome.matched_value,
            uniqueid=uniqueid,
            channel=channel,
            caller=caller,
            finish_reason=finish_reason,
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


def _capture_audio_result(
    *,
    capture_audio: Callable[[int, int, int], bytes | CaptureResult] | None,
    config: AppConfig,
) -> CaptureResult:
    if capture_audio is None:
        return capture_eagi_audio_result(
            fd=3,
            listen_seconds=config.ivr.listen_seconds,
            sample_rate=config.ivr.sample_rate,
            vad_enabled=config.ivr.vad_enabled,
            min_speech_ms=config.ivr.min_speech_ms,
            silence_after_speech_ms=config.ivr.silence_after_speech_ms,
            rms_speech_threshold=config.ivr.rms_speech_threshold,
        )

    captured = capture_audio(3, config.ivr.listen_seconds, config.ivr.sample_rate)
    if isinstance(captured, CaptureResult):
        return captured

    captured_audio = cast(bytes, captured)
    rms_value = calculate_rms(captured_audio)
    return CaptureResult(
        audio_bytes=captured_audio,
        bytes_read=len(captured_audio),
        duration_ms=int((len(captured_audio) / (config.ivr.sample_rate * 2)) * 1000),
        speech_started=rms_value >= config.ivr.rms_speech_threshold,
        finish_reason="legacy_capture",
        silence_ms=0,
        average_rms=rms_value,
        max_rms=rms_value,
    )


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
    finish_reason: str,
) -> None:
    masked_transcript = _mask_text_for_logging(transcript, config.logging.mask_phone_numbers)
    matched_phrase_fragment = _format_matched_phrase(
        matched_phrase,
        mask_phone_numbers=config.logging.mask_phone_numbers,
    )
    masked_channel = _mask_log_value(channel, config.logging.mask_phone_numbers)
    masked_caller = _mask_log_value(caller, config.logging.mask_phone_numbers)
    if config.logging.log_transcript and transcript:
        verbose_message = (
            f"VOSK intent={intent} source={source} "
            f"confidence={confidence:.2f} transcript={masked_transcript}"
        )
        _safe_verbose(session, logger, verbose_message, 1)
        logger.info(
            (
                "Fin EAGI intent=%s source=%s confidence=%.2f text=%s "
                "uniqueid=%s channel=%s caller=%s stop_reason=%s%s"
            ),
            intent,
            source,
            confidence,
            masked_transcript,
            uniqueid,
            masked_channel,
            masked_caller,
            finish_reason,
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
        (
            "Fin EAGI intent=%s source=%s confidence=%.2f "
            "uniqueid=%s channel=%s caller=%s stop_reason=%s%s"
        ),
        intent,
        source,
        confidence,
        uniqueid,
        masked_channel,
        masked_caller,
        finish_reason,
        matched_phrase_fragment,
    )


def _redirect_console_logging_to_stderr(logger: logging.Logger) -> None:
    for handler in logger.handlers:
        if type(handler) is logging.StreamHandler:
            handler.setStream(sys.stderr)


def _format_matched_phrase(
    matched_phrase: str | None,
    *,
    mask_phone_numbers: bool,
) -> str:
    if not matched_phrase:
        return ""
    masked_phrase = _mask_text_for_logging(matched_phrase, mask_phone_numbers)
    return f" matched_phrase={masked_phrase}"


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


def _log_vosk_debug(
    *,
    logger: logging.Logger,
    config: AppConfig,
    raw_messages: tuple[dict[str, object], ...],
) -> None:
    if not raw_messages:
        return

    partials = [
        _mask_text_for_logging(
            sanitize_channel_value(str(message.get("partial", "")).strip()),
            config.logging.mask_phone_numbers,
        )
        for message in raw_messages
        if str(message.get("partial", "")).strip()
    ]
    final_texts = [
        _mask_text_for_logging(
            sanitize_channel_value(str(message.get("text", "")).strip()),
            config.logging.mask_phone_numbers,
        )
        for message in raw_messages
        if str(message.get("text", "")).strip()
    ]
    logger.debug(
        "Vosk mensajes=%s partials=%s textos_finales=%s",
        len(raw_messages),
        len(partials),
        len(final_texts),
    )
    if not config.logging.log_transcript:
        return

    relevant_partials = partials[-3:]
    final_text = final_texts[-1] if final_texts else ""
    if relevant_partials or final_text:
        logger.debug(
            "Vosk partials_relevantes=%s texto_final=%s",
            relevant_partials,
            final_text,
        )


def _resolve_finish_reason(capture_finish_reason: str, outcome_finish_reason: str) -> str:
    if outcome_finish_reason in {"dtmf", "early_intent", "error"}:
        return outcome_finish_reason
    if capture_finish_reason in {"silence_after_speech", "timeout", "no_audio"}:
        return capture_finish_reason
    return outcome_finish_reason


def _maybe_dump_audio_bytes(
    *,
    audio_bytes: bytes,
    config: AppConfig,
    logger: logging.Logger,
    uniqueid: str,
    caller: str,
) -> None:
    if not config.logging.debug_audio_dump_enabled or not audio_bytes:
        return

    dump_dir = Path(config.logging.debug_audio_dump_dir).expanduser()
    dump_path = dump_dir / _build_audio_dump_filename(
        uniqueid=uniqueid,
        caller=caller,
        mask_phone_numbers=config.logging.mask_phone_numbers,
    )
    try:
        dump_dir.mkdir(parents=True, exist_ok=True)
        dump_path.write_bytes(audio_bytes)
    except OSError as exc:
        logger.warning("No fue posible guardar audio debug EAGI en %s: %s", dump_path, exc)
        return

    logger.debug("Audio debug EAGI guardado path=%s bytes=%s", dump_path, len(audio_bytes))


def _build_audio_dump_filename(
    *,
    uniqueid: str,
    caller: str,
    mask_phone_numbers: bool,
) -> str:
    safe_uniqueid = _safe_filename_fragment(uniqueid) or "unknown"
    caller_fragment = _mask_log_value(caller, mask_phone_numbers)
    safe_caller = _safe_filename_fragment(caller_fragment)
    if safe_caller:
        return f"eagi-{safe_uniqueid}-caller-{safe_caller}.raw"
    return f"eagi-{safe_uniqueid}.raw"


def _mask_log_value(value: str, mask_phone_numbers: bool) -> str:
    if not value:
        return ""
    if not mask_phone_numbers:
        return value
    return mask_sensitive_phone_numbers(value)


def _mask_text_for_logging(value: str, mask_phone_numbers: bool) -> str:
    compact_value = sanitize_channel_value(value)
    if not compact_value:
        return ""
    if not mask_phone_numbers:
        return compact_value
    return sanitize_channel_value(mask_sensitive_data(compact_value))


def _safe_filename_fragment(value: str) -> str:
    collapsed = SAFE_FILENAME_PATTERN.sub("_", value.strip())
    return collapsed.strip("_")
