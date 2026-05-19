from __future__ import annotations

import io
import logging

from vicidial_vosk_cobranza_ivr.app import _log_result, run_eagi_session
from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    AsteriskSettings,
    AudioSettings,
    IvrSettings,
    LoggingSettings,
    VoskSettings,
)
from vicidial_vosk_cobranza_ivr.intent_classifier import IntentClassifier
from vicidial_vosk_cobranza_ivr.service import CobranzaIvrService
from vicidial_vosk_cobranza_ivr.vosk_client import (
    RecognitionResult,
    VoskClient,
    VoskConnectionError,
    VoskTimeoutError,
)


class FakeSession:
    def __init__(
        self,
        environment: dict[str, str],
        set_variable_response: str = "200 result=1",
    ) -> None:
        self.environment = environment
        self.set_variable_response = set_variable_response
        self.variables: dict[str, str] = {}
        self.verbose_messages: list[tuple[str, int]] = []

    def read_environment(self) -> dict[str, str]:
        return self.environment

    def set_variable(self, name: str, value: str) -> str:
        self.variables[name] = value
        return self.set_variable_response

    def verbose(self, message: str, level: int = 1) -> None:
        self.verbose_messages.append((message, level))


class StubVoskClient(VoskClient):
    def __init__(
        self,
        result: RecognitionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__("ws://test.invalid")
        self.result = result
        self.error = error
        self.calls = 0

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int) -> RecognitionResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def build_config() -> AppConfig:
    return AppConfig(
        audio=AudioSettings(min_rms=150.0),
        ivr=IvrSettings(
            listen_seconds=4,
            retry_attempts=1,
            default_intent="DUDA",
            allow_dtmf_fallback=True,
            max_dtmf_wait_ms=5000,
            dtmf_map={"1": "SI", "2": "NO"},
        ),
        asterisk=AsteriskSettings(
            app_name="vicidial-vosk-cobranza-ivr",
            channel_variable_name="VOSK_INTENT",
            transfer_context="default",
            lawyer_destination_type="ingroup",
            lawyer_destination="INGROUP_ABOGADOS",
            final_disposition_yes="YES",
            final_disposition_no="NO",
            final_disposition_unknown="UNKNOWN",
        ),
        vosk=VoskSettings(
            websocket_url="ws://127.0.0.1:2700",
            sample_rate=8000,
            audio_format="s16le",
            language="es",
            websocket_timeout_seconds=10,
        ),
        logging=LoggingSettings(
            enabled=False,
            log_level="INFO",
            log_path="./logs/test.log",
            log_transcript=False,
            mask_phone_numbers=True,
            rotate_max_bytes=10485760,
            rotate_backup_count=10,
        ),
        intents={
            "SI": ["si", "quiero hablar", "comuniqueme"],
            "NO": ["no", "no quiero"],
            "DUDA": ["quien habla", "no entiendo", "no se"],
            "SILENCIO": [],
        },
    )


def build_service(vosk_client: VoskClient) -> CobranzaIvrService:
    config = build_config()
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
    )
    logger = logging.getLogger("test_eagi_app.service")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return CobranzaIvrService(
        config=config,
        classifier=classifier,
        vosk_client=vosk_client,
        logger=logger,
    )


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(logging.NullHandler())
    return logger


def test_run_eagi_session_prefers_dtmf_over_vosk() -> None:
    session = FakeSession({"agi_arg_1": "1", "agi_channel": "SIP/test-1", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="no", raw_messages=[], confidence=0.9)
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.dtmf")

    def fail_capture(fd: int, listen_seconds: int, sample_rate: int) -> bytes:
        raise AssertionError("No deberia capturar audio cuando el DTMF ya coincide")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=fail_capture,
        environment=session.environment,
    )

    assert result == 0
    assert vosk_client.calls == 0
    assert session.variables["VOSK_INTENT"] == "SI"
    assert session.variables["VOSK_TEXT"] == ""
    assert session.variables["VOSK_CONFIDENCE"] == "1.00"
    assert session.variables["VOSK_SOURCE"] == "dtmf"


def test_run_eagi_session_falls_back_to_voice_when_dtmf_is_invalid() -> None:
    session = FakeSession(
        {"agi_arg_1": "9", "agi_channel": "SIP/test-invalid", "agi_callerid": "123456"}
    )
    vosk_client = StubVoskClient(
        result=RecognitionResult(
            transcript="si quiero hablar",
            raw_messages=[{"text": "si quiero hablar"}],
            confidence=0.88,
        )
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.invalid_dtmf")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\xff\x7f" * 400,
        environment=session.environment,
    )

    assert result == 0
    assert vosk_client.calls == 1
    assert session.variables["VOSK_INTENT"] == "SI"
    assert session.variables["VOSK_SOURCE"] == "speech"


def test_run_eagi_session_marks_silence_when_audio_is_empty() -> None:
    session = FakeSession({"agi_channel": "SIP/test-2", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="si", raw_messages=[], confidence=0.95)
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.empty_audio")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"",
        environment=session.environment,
    )

    assert result == 0
    assert vosk_client.calls == 0
    assert session.variables["VOSK_INTENT"] == "SILENCIO"
    assert session.variables["VOSK_TEXT"] == ""
    assert session.variables["VOSK_CONFIDENCE"] == "0.00"
    assert session.variables["VOSK_SOURCE"] == "silence"


def test_run_eagi_session_marks_silence_when_rms_is_below_threshold() -> None:
    session = FakeSession({"agi_channel": "SIP/test-rms", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="si", raw_messages=[], confidence=0.95)
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.low_rms")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\x01\x00" * 400,
        environment=session.environment,
    )

    assert result == 0
    assert vosk_client.calls == 0
    assert session.variables["VOSK_INTENT"] == "SILENCIO"
    assert session.variables["VOSK_SOURCE"] == "silence"


def test_run_eagi_session_marks_error_when_vosk_times_out() -> None:
    session = FakeSession({"agi_channel": "SIP/test-timeout", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(error=VoskTimeoutError("timeout"))
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.timeout")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\xff\x7f" * 400,
        environment=session.environment,
    )

    assert result == 1
    assert vosk_client.calls == 1
    assert session.variables["VOSK_INTENT"] == "DUDA"
    assert session.variables["VOSK_TEXT"] == ""
    assert session.variables["VOSK_CONFIDENCE"] == "0.00"
    assert session.variables["VOSK_SOURCE"] == "error"


def test_run_eagi_session_marks_error_when_vosk_fails() -> None:
    session = FakeSession({"agi_channel": "SIP/test-3", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(error=VoskConnectionError("down"))
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.error")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\xff\x7f" * 400,
        environment=session.environment,
    )

    assert result == 1
    assert vosk_client.calls == 1
    assert session.variables["VOSK_INTENT"] == "DUDA"
    assert session.variables["VOSK_TEXT"] == ""
    assert session.variables["VOSK_CONFIDENCE"] == "0.00"
    assert session.variables["VOSK_SOURCE"] == "error"


def test_run_eagi_session_classifies_speech_and_sets_confidence() -> None:
    session = FakeSession({"agi_channel": "SIP/test-4", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(
        result=RecognitionResult(
            transcript="sí quiero hablar",
            raw_messages=[{"text": "sí quiero hablar"}],
            confidence=0.88,
        )
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.speech")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\xff\x7f" * 400,
        environment=session.environment,
    )

    assert result == 0
    assert vosk_client.calls == 1
    assert session.variables["VOSK_INTENT"] == "SI"
    assert session.variables["VOSK_TEXT"] == "si quiero hablar"
    assert session.variables["VOSK_CONFIDENCE"] == "0.86"
    assert session.variables["VOSK_SOURCE"] == "speech"


def test_log_result_omits_transcript_when_log_transcript_is_disabled() -> None:
    session = FakeSession({"agi_channel": "SIP/test-logs", "agi_callerid": "3001234567"})
    config = build_config()
    logger = logging.getLogger("test_eagi_app.logs")
    logger.handlers.clear()
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    _log_result(
        session=session,
        logger=logger,
        config=config,
        intent="SI",
        source="speech",
        confidence=0.91,
        transcript="si quiero hablar con el abogado",
        matched_phrase="quiero hablar",
        uniqueid="1716123456.321",
        channel="SIP/3001234567-00000001",
        caller="3001234567",
    )

    logged = stream.getvalue()

    assert "si quiero hablar con el abogado" not in logged
    assert "transcript=" not in logged
    assert session.verbose_messages == [("VOSK intent=SI source=speech confidence=0.91", 1)]
