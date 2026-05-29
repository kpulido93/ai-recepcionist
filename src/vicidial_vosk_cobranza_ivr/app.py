from __future__ import annotations

import inspect
import logging
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from vicidial_vosk_cobranza_ivr.agi_runtime import AgiIoError, AgiSession
from vicidial_vosk_cobranza_ivr.audio import (
    CaptureResult,
    calculate_rms,
    capture_eagi_audio_result,
)
from vicidial_vosk_cobranza_ivr.blocklist import BlocklistMatcher
from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    ListenAttemptSettings,
    RuntimePaths,
    load_app_config,
    resolve_runtime_paths,
)
from vicidial_vosk_cobranza_ivr.decision_engine import DecisionEngine
from vicidial_vosk_cobranza_ivr.intent_classifier import (
    IntentClassifier,
    intent_value,
)
from vicidial_vosk_cobranza_ivr.logging_utils import (
    configure_logging,
    mask_sensitive_data,
)
from vicidial_vosk_cobranza_ivr.logging_utils import (
    mask_phone_numbers as mask_sensitive_phone_numbers,
)
from vicidial_vosk_cobranza_ivr.reporting import (
    append_final_call_event,
    build_final_call_event,
)
from vicidial_vosk_cobranza_ivr.service import CobranzaIvrService, ProcessingOutcome
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient

SAFE_AGI_VALUE_LENGTH = 2048
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
VALID_LISTEN_PROFILE_NAMES = frozenset(
    {
        "first_attempt",
        "retry_attempt",
        "objection_probe",
        "greeting_confirm",
        "main_question",
        "offer_confirm",
    }
)


@dataclass(frozen=True)
class RetryContext:
    retry_count: int
    try_value: int
    vosk_try_value: int


def build_service(
    config: AppConfig,
    logger: logging.Logger,
    audio_sender: Callable[[object, bytes], None] | None = None,
) -> CobranzaIvrService:
    blocklist_matcher = BlocklistMatcher.from_paths()
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
        semantic_config={
            "enabled": config.semantic_classifier.enabled,
            "fuzzy_enabled": config.semantic_classifier.fuzzy_enabled,
            "semantic_enabled": config.semantic_classifier.semantic_enabled,
            "fuzzy_threshold": config.semantic_classifier.fuzzy_threshold,
            "semantic_threshold": config.semantic_classifier.semantic_threshold,
            "min_confidence": config.semantic_classifier.min_confidence,
        },
        semantic_intents=config.semantic_intents,
        blocklist_matcher=blocklist_matcher,
    )
    decision_engine = DecisionEngine.from_yaml()
    vosk_client = VoskClient(
        websocket_url=config.vosk.websocket_url,
        timeout_seconds=config.vosk.websocket_timeout_seconds,
        audio_sender=audio_sender,
        early_detection_enabled=config.ivr.early_detection_enabled,
        early_detection_min_audio_ms=config.ivr.early_detection_min_audio_ms,
        early_detection_min_chars=config.ivr.early_detection_min_chars,
        early_intent_detector=classifier.detect_early_intent,
    )
    return CobranzaIvrService(
        config=config,
        classifier=classifier,
        decision_engine=decision_engine,
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
        config = _load_runtime_app_config(runtime_paths, fallback_logger)
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
    attempts = _resolve_attempts(call_environment)
    masked_channel = _mask_log_value(channel, config.logging.mask_phone_numbers)
    masked_caller = _mask_log_value(caller, config.logging.mask_phone_numbers)
    retry_context = _resolve_retry_context(session, call_environment, logger)
    flow_stage = _resolve_flow_stage(session, call_environment, logger)
    requested_listen_profile = _resolve_listen_profile_name(session, call_environment, logger)
    logger.info(
        (
            "Inicio EAGI uniqueid=%s channel=%s caller=%s TRY=%s VOSK_TRY=%s "
            "flow_stage=%s listen_profile=%s"
        ),
        uniqueid,
        masked_channel,
        masked_caller,
        retry_context.try_value,
        retry_context.vosk_try_value,
        flow_stage or "",
        requested_listen_profile or "",
    )

    try:
        outcome: ProcessingOutcome | None = None
        transcript = ""
        finish_reason = "error"
        capture_result: CaptureResult | None = None
        if dtmf and dtmf in config.ivr.dtmf_map:
            outcome = service.classify_audio_bytes(
                b"",
                config.ivr.sample_rate,
                dtmf=dtmf,
                retry_count=retry_context.retry_count,
                flow_stage=flow_stage,
            )
            capture_finish_reason = "dtmf"
        else:
            capture_result = _capture_audio_result(
                capture_audio=capture_audio,
                config=config,
                retry_count=retry_context.retry_count,
                requested_profile_name=requested_listen_profile,
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
                retry_count=retry_context.retry_count,
                flow_stage=flow_stage,
            )
            capture_finish_reason = capture_result.finish_reason

        transcript = sanitize_channel_value(outcome.transcript)
        finish_reason = _resolve_finish_reason(capture_finish_reason, outcome.finish_reason)
        _log_vosk_debug(logger=logger, config=config, raw_messages=outcome.raw_messages)
        _log_listen_diagnostics(
            logger=logger,
            config=config,
            retry_count=retry_context.retry_count,
            try_value=retry_context.try_value,
            vosk_try_value=retry_context.vosk_try_value,
            flow_stage=flow_stage,
            capture_result=capture_result,
            finish_reason=finish_reason,
            transcript=transcript,
            raw_messages=outcome.raw_messages,
            source=outcome.source,
            error_reason=outcome.reason if outcome.source == "error" else None,
        )
        write_ok = _write_agi_result(
            session=session,
            channel_variable_name=config.asterisk.channel_variable_name,
            intent=intent_value(outcome.intent),
            text=transcript,
            confidence=f"{outcome.confidence:.2f}",
            source=outcome.source,
            decision=outcome.decision,
            transfer_eligible="1" if outcome.transfer_eligible else "0",
            block_reason=outcome.block_reason or "",
            final_disposition=outcome.final_disposition,
            matched_value=sanitize_channel_value(outcome.matched_value or ""),
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
        _write_final_event(
            logger=logger,
            config=config,
            uniqueid=uniqueid,
            channel=channel,
            caller=caller,
            intent=intent_value(outcome.intent),
            confidence=outcome.confidence,
            matched_phrase=outcome.matched_value,
            transcript=transcript,
            finish_reason=finish_reason,
            attempts=attempts,
            source=outcome.source,
        )
        if not write_ok:
            logger.warning("Asterisk no confirmo SET VARIABLE para todas las variables VOSK.")
            return 1
        return 1 if outcome.source == "error" else 0
    except AgiIoError as exc:
        logger.warning("Canal AGI no disponible para devolver resultado: %s", exc)
        if outcome is not None:
            _write_final_event(
                logger=logger,
                config=config,
                uniqueid=uniqueid,
                channel=channel,
                caller=caller,
                intent=intent_value(outcome.intent),
                confidence=outcome.confidence,
                matched_phrase=outcome.matched_value,
                transcript=transcript,
                finish_reason=finish_reason,
                attempts=attempts,
                source=outcome.source,
            )
        else:
            _write_final_event(
                logger=logger,
                config=config,
                uniqueid=uniqueid,
                channel=channel,
                caller=caller,
                intent=config.ivr.default_intent,
                confidence=0.0,
                matched_phrase=None,
                transcript="",
                finish_reason="error",
                attempts=attempts,
                source="error",
            )
        return 1
    except Exception:
        logger.exception(
            "Error durante la ejecucion EAGI stage=%s TRY=%s VOSK_TRY=%s",
            flow_stage or "",
            retry_context.try_value,
            retry_context.vosk_try_value,
        )
        _safe_write_error_result(
            session,
            config.asterisk.channel_variable_name,
            config.ivr.default_intent,
        )
        _write_final_event(
            logger=logger,
            config=config,
            uniqueid=uniqueid,
            channel=channel,
            caller=caller,
            intent=config.ivr.default_intent,
            confidence=0.0,
            matched_phrase=None,
            transcript="",
            finish_reason="error",
            attempts=attempts,
            source="error",
        )
        return 1


def sanitize_channel_value(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:SAFE_AGI_VALUE_LENGTH]


def _load_runtime_app_config(
    runtime_paths: RuntimePaths,
    fallback_logger: logging.Logger,
) -> AppConfig:
    try:
        signature = inspect.signature(load_app_config)
    except (TypeError, ValueError):
        signature = None

    if signature is None or "logging_config_path" in signature.parameters:
        try:
            return load_app_config(
                runtime_paths.config_path,
                runtime_paths.intents_path,
                runtime_paths.logging_path,
            )
        except TypeError as exc:
            fallback_logger.warning(
                "load_app_config incompatible con logging_path; reintentando sin ese argumento: %s",
                exc,
            )

    if signature is not None and "logging_config_path" not in signature.parameters:
        fallback_logger.warning(
            "load_app_config sin soporte logging_path detectado; usando compatibilidad temporal."
        )

    return load_app_config(runtime_paths.config_path, runtime_paths.intents_path)


def _resolve_flow_stage(
    session: AgiSession,
    call_environment: Mapping[str, str],
    logger: logging.Logger,
) -> str | None:
    for variable_name in ("agi_arg_3", "agi_arg_4"):
        flow_stage = call_environment.get(variable_name, "").strip()
        if flow_stage:
            return flow_stage

    for variable_name in ("VOSK_FLOW_STAGE", "vosk_flow_stage"):
        flow_stage = call_environment.get(variable_name, "").strip()
        if flow_stage:
            return flow_stage

    session_get_variable = getattr(session, "get_variable", None)
    if not callable(session_get_variable):
        return None

    try:
        resolved_value = session_get_variable("VOSK_FLOW_STAGE")
    except AgiIoError as exc:
        logger.debug("No fue posible leer VOSK_FLOW_STAGE desde AGI: %s", exc)
        return None

    if resolved_value is None:
        return None
    normalized_value = resolved_value.strip()
    return normalized_value or None


def _capture_audio_result(
    *,
    capture_audio: Callable[[int, int, int], bytes | CaptureResult] | None,
    config: AppConfig,
    retry_count: int,
    requested_profile_name: str | None,
) -> CaptureResult:
    active_listen_profile = _resolve_listen_attempt_settings(
        config=config,
        retry_count=retry_count,
        requested_profile_name=requested_profile_name,
    )
    if capture_audio is None:
        return capture_eagi_audio_result(
            fd=3,
            listen_seconds=active_listen_profile.max_listen_seconds,
            sample_rate=config.ivr.sample_rate,
            vad_enabled=config.ivr.vad_enabled,
            min_speech_ms=active_listen_profile.min_speech_ms,
            silence_after_speech_ms=active_listen_profile.silence_after_speech_ms,
            rms_speech_threshold=config.ivr.rms_speech_threshold,
            initial_silence_timeout_ms=int(active_listen_profile.initial_timeout_seconds * 1000),
        )

    captured = capture_audio(
        3,
        active_listen_profile.max_listen_seconds,
        config.ivr.sample_rate,
    )
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
    decision: str,
    transfer_eligible: str,
    block_reason: str,
    final_disposition: str,
    matched_value: str,
) -> bool:
    responses = [
        agi_set_variable(session, "VOSK_TEXT", text),
        agi_set_variable(session, "VOSK_INTENT", intent),
        agi_set_variable(session, "VOSK_CONFIDENCE", confidence),
        agi_set_variable(session, "VOSK_SOURCE", source),
        agi_set_variable(session, "VOSK_DECISION", decision),
        agi_set_variable(session, "VOSK_TRANSFER_ELIGIBLE", transfer_eligible),
        agi_set_variable(session, "VOSK_BLOCK_REASON", block_reason),
        agi_set_variable(session, "VOSK_FINAL_DISPOSITION", final_disposition),
        agi_set_variable(session, "VOSK_MATCHED_VALUE", matched_value),
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
            decision="RETRY",
            transfer_eligible="0",
            block_reason="error",
            final_disposition="VOZ_ERROR_CLASIFICACION",
            matched_value="",
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


def _write_final_event(
    *,
    logger: logging.Logger,
    config: AppConfig,
    uniqueid: str,
    channel: str,
    caller: str,
    intent: str,
    confidence: float,
    matched_phrase: str | None,
    transcript: str,
    finish_reason: str,
    attempts: int | None,
    source: str,
) -> None:
    event = build_final_call_event(
        uniqueid=uniqueid,
        channel=channel,
        caller=caller,
        intent=intent,
        confidence=confidence,
        matched_phrase=matched_phrase,
        text=transcript,
        stop_reason=finish_reason,
        attempts=attempts,
        source=source,
        mask_phone_numbers=config.logging.mask_phone_numbers,
    )
    append_final_call_event(config.logging.events_path, event, logger)


def _resolve_attempts(environment: Mapping[str, str]) -> int | None:
    for key in ("agi_arg_2", "agi_attempts", "agi_try", "TRY"):
        raw_value = environment.get(key, "").strip()
        if not raw_value:
            continue
        try:
            return int(raw_value)
        except ValueError:
            continue
    return None


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


def _resolve_retry_context(
    session: AgiSession,
    environment: dict[str, str],
    logger: logging.Logger,
) -> RetryContext:
    try_value = _resolve_counter_value(
        session=session,
        environment=environment,
        variable_name="TRY",
        logger=logger,
    )
    vosk_try_value = _resolve_counter_value(
        session=session,
        environment=environment,
        variable_name="VOSK_TRY",
        logger=logger,
    )
    retry_count = _parse_retry_count_from_mapping(environment, logger)
    if retry_count is None:
        for variable_name in ("TRY", "VOSK_TRY", "IVR_RETRY_COUNT"):
            variable_value = _read_channel_variable(session, variable_name, logger)
            retry_count = _parse_retry_count_candidate(variable_value, variable_name, logger)
            if retry_count is not None:
                break

    return RetryContext(
        retry_count=0 if retry_count is None else retry_count,
        try_value=try_value,
        vosk_try_value=vosk_try_value,
    )


def _resolve_counter_value(
    *,
    session: AgiSession,
    environment: dict[str, str],
    variable_name: str,
    logger: logging.Logger,
) -> int:
    if variable_name in environment:
        return _normalize_counter_value(environment.get(variable_name), variable_name, logger)

    variable_value = _read_channel_variable(session, variable_name, logger)
    return _normalize_counter_value(variable_value, variable_name, logger)


def _parse_retry_count_from_mapping(
    environment: dict[str, str],
    logger: logging.Logger,
) -> int | None:
    for key in ("TRY", "VOSK_TRY", "IVR_RETRY_COUNT", "agi_arg_2"):
        retry_count = _parse_retry_count_candidate(environment.get(key), key, logger)
        if retry_count is not None:
            return retry_count
    return None


def _parse_retry_count_candidate(
    raw_value: str | None,
    variable_name: str,
    logger: logging.Logger,
) -> int | None:
    if raw_value is None:
        return None
    stripped_value = raw_value.strip()
    if not stripped_value:
        return None
    return _normalize_counter_value(stripped_value, variable_name, logger)


def _normalize_counter_value(
    raw_value: str | None,
    variable_name: str,
    logger: logging.Logger,
) -> int:
    if raw_value is None:
        return 0
    stripped_value = raw_value.strip()
    if not stripped_value:
        return 0
    try:
        return max(0, int(stripped_value))
    except ValueError:
        logger.warning(
            "Variable de reintento invalida variable=%s value=%s; usando 0",
            variable_name,
            raw_value,
        )
        return 0


def _read_channel_variable(
    session: AgiSession,
    variable_name: str,
    logger: logging.Logger,
) -> str | None:
    try:
        response = session.command(f"GET VARIABLE {variable_name}")
    except AgiIoError as exc:
        logger.debug("No fue posible leer variable de canal %s: %s", variable_name, exc)
        return None

    return _parse_get_variable_response(response)


def _parse_get_variable_response(response: str) -> str | None:
    if "result=0" in response:
        return None
    if "(" not in response or ")" not in response:
        return None
    raw_value = response.rsplit("(", 1)[1].rsplit(")", 1)[0].strip()
    return raw_value or None


def _resolve_listen_attempt_settings(
    *,
    config: AppConfig,
    retry_count: int,
    requested_profile_name: str | None = None,
) -> ListenAttemptSettings:
    if requested_profile_name == "first_attempt":
        return config.ivr.listen_profiles.first_attempt
    if requested_profile_name == "retry_attempt":
        return config.ivr.listen_profiles.retry_attempt
    if requested_profile_name == "objection_probe":
        return config.ivr.listen_profiles.objection_probe
    if requested_profile_name == "greeting_confirm":
        return config.ivr.listen_profiles.greeting_confirm
    if requested_profile_name == "main_question":
        return config.ivr.listen_profiles.main_question
    if requested_profile_name == "offer_confirm":
        return config.ivr.listen_profiles.offer_confirm
    if retry_count <= 0:
        return config.ivr.listen_profiles.first_attempt
    return config.ivr.listen_profiles.retry_attempt


def _resolve_listen_profile_name(
    session: AgiSession,
    call_environment: Mapping[str, str],
    logger: logging.Logger,
) -> str | None:
    raw_profile = ""
    for variable_name in ("IVR_LISTEN_PROFILE", "ivr_listen_profile"):
        candidate = call_environment.get(variable_name, "").strip()
        if candidate:
            raw_profile = candidate
            break

    if not raw_profile:
        raw_profile = _read_channel_variable(session, "IVR_LISTEN_PROFILE", logger) or ""

    if not raw_profile:
        return None

    normalized_profile = raw_profile.strip().lower()
    if normalized_profile in VALID_LISTEN_PROFILE_NAMES:
        return normalized_profile

    logger.warning(
        "Valor invalido de IVR_LISTEN_PROFILE=%s; usando fallback seguro por TRY/VOSK_TRY.",
        raw_profile,
    )
    return None


def _log_listen_diagnostics(
    *,
    logger: logging.Logger,
    config: AppConfig,
    retry_count: int,
    try_value: int,
    vosk_try_value: int,
    flow_stage: str | None,
    capture_result: CaptureResult | None,
    finish_reason: str,
    transcript: str,
    raw_messages: tuple[dict[str, object], ...],
    source: str,
    error_reason: str | None,
) -> None:
    had_audio = capture_result is not None and capture_result.bytes_read > 0
    duration_ms = capture_result.duration_ms if capture_result is not None else 0
    speech_started = capture_result.speech_started if capture_result is not None else False
    masked_transcript = _mask_text_for_logging(transcript, config.logging.mask_phone_numbers)
    early_partial = _extract_last_partial(raw_messages) if finish_reason == "early_intent" else ""
    masked_early_partial = _mask_text_for_logging(
        early_partial,
        config.logging.mask_phone_numbers,
    )
    logger.info(
        (
            "EAGI listen_diagnostic stage=%s TRY=%s VOSK_TRY=%s retry_count=%s had_audio=%s "
            "speech_started=%s duration_ms=%s stop_reason=%s transcript=%s early_partial=%s"
        ),
        flow_stage or "",
        try_value,
        vosk_try_value,
        retry_count,
        had_audio,
        speech_started,
        duration_ms,
        finish_reason,
        masked_transcript or "-",
        masked_early_partial or "-",
    )
    if error_reason is None:
        return

    logger.warning(
        (
            "EAGI listen_error stage=%s TRY=%s VOSK_TRY=%s had_audio=%s speech_started=%s "
            "duration_ms=%s stop_reason=%s source=%s transcript=%s exception=%s"
        ),
        flow_stage or "",
        try_value,
        vosk_try_value,
        had_audio,
        speech_started,
        duration_ms,
        finish_reason,
        source,
        masked_transcript or "-",
        error_reason,
    )


def _extract_last_partial(raw_messages: tuple[dict[str, object], ...]) -> str:
    for message in reversed(raw_messages):
        partial = sanitize_channel_value(str(message.get("partial", "")).strip())
        if partial:
            return partial
    return ""
