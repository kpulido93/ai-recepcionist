from __future__ import annotations

import io
import logging
from pathlib import Path

from vicidial_vosk_cobranza_ivr.app import _log_result, run_eagi_session
from vicidial_vosk_cobranza_ivr.audio import CaptureResult
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
    VoskProtocolError,
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
            sample_rate=8000,
            retry_attempts=1,
            default_intent="DUDA",
            allow_dtmf_fallback=True,
            early_detection_enabled=True,
            early_detection_min_audio_ms=250,
            early_detection_min_chars=2,
            vad_enabled=True,
            min_speech_ms=250,
            silence_after_speech_ms=700,
            rms_speech_threshold=250.0,
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
            debug_audio_dump_enabled=False,
            debug_audio_dump_dir="/tmp",
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


def test_run_eagi_session_marks_error_when_vosk_protocol_is_invalid() -> None:
    session = FakeSession({"agi_channel": "SIP/test-protocol", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(error=VoskProtocolError("bad frame"))
    service = build_service(vosk_client)
    config = build_config()
    logger = build_logger("test_eagi_app.protocol_error")

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


def test_run_eagi_session_logs_vad_metrics_and_prefers_early_intent_stop_reason() -> None:
    session = FakeSession({"agi_channel": "SIP/test-vad", "agi_callerid": "123456"})
    vosk_client = StubVoskClient(
        result=RecognitionResult(
            transcript="si",
            raw_messages=[{"partial": "si"}],
            confidence=1.0,
            early_intent="SI",
            early_matched_phrase="si",
            finish_reason="early_intent",
        )
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = logging.getLogger("test_eagi_app.vad_stop_reason")
    logger.handlers.clear()
    logger.propagate = False
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))
    logger.setLevel(logging.DEBUG)

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: CaptureResult(
            audio_bytes=b"\xff\x7f" * 2400,
            bytes_read=4800,
            duration_ms=300,
            speech_started=True,
            finish_reason="silence_after_speech",
            silence_ms=700,
            average_rms=12000.0,
            max_rms=32767.0,
        ),
        environment=session.environment,
    )

    logged = stream.getvalue()

    assert result == 0
    assert "speech_started=True" in logged
    assert "duration_ms=300" in logged
    assert "silence_ms=700" in logged
    assert "rms_avg=12000.00" in logged
    assert "rms_max=32767.00" in logged
    assert "stop_reason=early_intent" in logged


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
        finish_reason="silence_after_speech",
    )

    logged = stream.getvalue()

    assert "si quiero hablar con el abogado" not in logged
    assert "transcript=" not in logged
    assert session.verbose_messages == [("VOSK intent=SI source=speech confidence=0.91", 1)]


def test_log_result_masks_transcript_and_logs_fin_eagi_when_enabled() -> None:
    session = FakeSession({"agi_channel": "SIP/test-mask", "agi_callerid": "3001234567"})
    base_config = build_config()
    config = AppConfig(
        audio=base_config.audio,
        ivr=base_config.ivr,
        asterisk=base_config.asterisk,
        vosk=base_config.vosk,
        logging=LoggingSettings(
            enabled=base_config.logging.enabled,
            log_level=base_config.logging.log_level,
            log_path=base_config.logging.log_path,
            log_transcript=True,
            mask_phone_numbers=True,
            debug_audio_dump_enabled=base_config.logging.debug_audio_dump_enabled,
            debug_audio_dump_dir=base_config.logging.debug_audio_dump_dir,
            rotate_max_bytes=base_config.logging.rotate_max_bytes,
            rotate_backup_count=base_config.logging.rotate_backup_count,
        ),
        intents=base_config.intents,
    )
    logger = logging.getLogger("test_eagi_app.logs_masked_transcript")
    logger.handlers.clear()
    logger.propagate = False
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))
    logger.setLevel(logging.INFO)

    _log_result(
        session=session,
        logger=logger,
        config=config,
        intent="CALLBACK",
        source="speech",
        confidence=0.80,
        transcript="llameme al 3001234567",
        matched_phrase="llameme al 3001234567",
        uniqueid="1716123456.654",
        channel="SIP/3001234567-00000002",
        caller="3001234567",
        finish_reason="timeout",
    )

    logged = stream.getvalue()

    assert "Fin EAGI" in logged
    assert "3001234567" not in logged
    assert "text=llameme al XXXXXXXX67" in logged
    assert "matched_phrase=llameme al XXXXXXXX67" in logged
    assert "stop_reason=timeout" in logged
    assert session.verbose_messages == [
        ("VOSK intent=CALLBACK source=speech confidence=0.80 transcript=llameme al XXXXXXXX67", 1)
    ]


def test_run_eagi_session_masks_caller_on_start_log() -> None:
    session = FakeSession(
        {
            "agi_channel": "SIP/3001234567-00000001",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.321",
        }
    )
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="", raw_messages=[], confidence=None)
    )
    service = build_service(vosk_client)
    config = build_config()
    logger = logging.getLogger("test_eagi_app.start_log_mask")
    logger.handlers.clear()
    logger.propagate = False
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))
    logger.setLevel(logging.INFO)

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"",
        environment=session.environment,
    )

    logged = stream.getvalue()

    assert result == 0
    assert "3001234567" not in logged
    assert "caller=XXXXXXXX67" in logged


def test_run_eagi_session_does_not_create_audio_dump_when_disabled(tmp_path: Path) -> None:
    session = FakeSession(
        {
            "agi_channel": "SIP/test-dump-off",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.321",
        }
    )
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="si", raw_messages=[{"text": "si"}], confidence=0.95)
    )
    service = build_service(vosk_client)
    config = build_config()
    dump_dir = tmp_path / "dumps-off"
    config = AppConfig(
        audio=config.audio,
        ivr=config.ivr,
        asterisk=config.asterisk,
        vosk=config.vosk,
        logging=LoggingSettings(
            enabled=config.logging.enabled,
            log_level=config.logging.log_level,
            log_path=config.logging.log_path,
            log_transcript=config.logging.log_transcript,
            mask_phone_numbers=config.logging.mask_phone_numbers,
            debug_audio_dump_enabled=False,
            debug_audio_dump_dir=str(dump_dir),
            rotate_max_bytes=config.logging.rotate_max_bytes,
            rotate_backup_count=config.logging.rotate_backup_count,
        ),
        intents=config.intents,
    )
    logger = build_logger("test_eagi_app.dump_disabled")

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\xff\x7f" * 400,
        environment=session.environment,
    )

    assert result == 0
    assert not dump_dir.exists() or list(dump_dir.iterdir()) == []


def test_run_eagi_session_creates_audio_dump_when_enabled(tmp_path: Path) -> None:
    session = FakeSession(
        {
            "agi_channel": "SIP/test-dump-on",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.321",
        }
    )
    vosk_client = StubVoskClient(
        result=RecognitionResult(transcript="si", raw_messages=[{"text": "si"}], confidence=0.95)
    )
    service = build_service(vosk_client)
    config = build_config()
    dump_dir = tmp_path / "dumps-on"
    config = AppConfig(
        audio=config.audio,
        ivr=config.ivr,
        asterisk=config.asterisk,
        vosk=config.vosk,
        logging=LoggingSettings(
            enabled=config.logging.enabled,
            log_level=config.logging.log_level,
            log_path=config.logging.log_path,
            log_transcript=config.logging.log_transcript,
            mask_phone_numbers=config.logging.mask_phone_numbers,
            debug_audio_dump_enabled=True,
            debug_audio_dump_dir=str(dump_dir),
            rotate_max_bytes=config.logging.rotate_max_bytes,
            rotate_backup_count=config.logging.rotate_backup_count,
        ),
        intents=config.intents,
    )
    logger = build_logger("test_eagi_app.dump_enabled")
    audio_bytes = b"\xff\x7f" * 400

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: audio_bytes,
        environment=session.environment,
    )

    dump_files = list(dump_dir.iterdir())

    assert result == 0
    assert len(dump_files) == 1
    assert dump_files[0].suffix == ".raw"
    assert "3001234567" not in dump_files[0].name
    assert dump_files[0].read_bytes() == audio_bytes
