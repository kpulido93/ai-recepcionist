from __future__ import annotations

import logging

from vicidial_vosk_cobranza_ivr.agi_runtime import AgiSession
from vicidial_vosk_cobranza_ivr.audio import capture_eagi_audio
from vicidial_vosk_cobranza_ivr.config import AppConfig, load_app_config, resolve_runtime_paths
from vicidial_vosk_cobranza_ivr.intent_classifier import Intent, IntentClassifier
from vicidial_vosk_cobranza_ivr.logging_utils import configure_logging
from vicidial_vosk_cobranza_ivr.service import CobranzaIvrService
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient


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
    runtime_paths = resolve_runtime_paths()
    config = load_app_config(runtime_paths.config_path, runtime_paths.intents_path)
    logger = configure_logging(config.logging, runtime_paths.logging_path)
    service = build_service(config=config, logger=logger)
    session = AgiSession()
    environment = session.read_environment()
    caller = environment.get("agi_callerid", "")
    channel = environment.get("agi_channel", "")
    dtmf = (environment.get("agi_arg_1", "") or "").strip() or None
    logger.info("Inicio EAGI channel=%s caller=%s", channel, caller)

    try:
        if dtmf:
            outcome = service.classify_audio_bytes(b"", config.vosk.sample_rate, dtmf=dtmf)
        else:
            audio_bytes = capture_eagi_audio(
                fd=3,
                listen_seconds=config.ivr.listen_seconds,
                sample_rate=config.vosk.sample_rate,
            )
            outcome = service.classify_audio_bytes(
                audio_bytes=audio_bytes,
                sample_rate=config.vosk.sample_rate,
            )
            if outcome.intent is Intent.SILENCIO and config.ivr.allow_dtmf_fallback:
                fallback_dtmf = session.wait_for_digit(config.ivr.max_dtmf_wait_ms)
                if fallback_dtmf:
                    outcome = service.classify_audio_bytes(
                        b"",
                        config.vosk.sample_rate,
                        dtmf=fallback_dtmf,
                    )

        transcript = sanitize_channel_value(outcome.transcript)
        session.set_variable(config.asterisk.channel_variable_name, outcome.intent.value)
        session.set_variable("VOSK_SOURCE", outcome.source)
        session.set_variable("VOSK_TRANSCRIPT", transcript)
        session.verbose(
            f"VOSK intent={outcome.intent.value} source={outcome.source} transcript={transcript}",
            1,
        )
        logger.info(
            "Intent=%s source=%s transcript=%s channel=%s caller=%s",
            outcome.intent.value,
            outcome.source,
            transcript,
            channel,
            caller,
        )
        return 0
    except Exception:
        logger.exception("Error durante la ejecucion EAGI")
        session.set_variable(config.asterisk.channel_variable_name, config.ivr.default_intent)
        session.set_variable("VOSK_SOURCE", "error")
        session.set_variable("VOSK_TRANSCRIPT", "")
        return 1


def sanitize_channel_value(value: str, max_length: int = 120) -> str:
    compact = " ".join(value.split())
    return compact[:max_length]
