from __future__ import annotations

import json
import logging
from io import StringIO

from websocket import ABNF, WebSocketConnectionClosedException

from vicidial_vosk_cobranza_ivr import vosk_client
from vicidial_vosk_cobranza_ivr.agi_runtime import AgiSession
from vicidial_vosk_cobranza_ivr.app import build_service, run_eagi_session
from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    AsteriskSettings,
    AudioSettings,
    IvrSettings,
    LoggingSettings,
    PromptsSettings,
    VoskSettings,
)


class FakeWebSocket:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.sent_messages: list[str] = []
        self.sent_binary: list[bytes] = []
        self.sent_opcodes: list[int | None] = []
        self.closed = False

    def send(self, payload: object, opcode: int | None = None) -> None:
        self.sent_opcodes.append(opcode)
        if opcode == ABNF.OPCODE_BINARY:
            assert isinstance(payload, bytes)
            self.sent_binary.append(payload)
            return

        assert isinstance(payload, str)
        self.sent_messages.append(payload)

    def settimeout(self, timeout: float) -> None:
        _ = timeout

    def recv(self) -> object:
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


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
            events_path="",
            log_transcript=False,
            mask_phone_numbers=True,
            debug_audio_dump_enabled=False,
            debug_audio_dump_dir="/tmp",
            rotate_max_bytes=10485760,
            rotate_backup_count=10,
        ),
        prompts=PromptsSettings(
            personalized_greeting_enabled=True,
            greeting_template=(
                "Hola {client_name}, nos comunicamos de SokaCorp por una gestion pendiente "
                "relacionada con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_template_without_name=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente relacionada con "
                "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_fallback=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente. "
                "¿Desea que le comuniquemos ahora? Le escucho."
            ),
            generated_audio_dir="/tmp/generated",
            generated_audio_playback_prefix="custom/generated",
            tts_provider="espeak-ng",
            tts_voice="es-la",
            cache_enabled=True,
            privacy_mode=False,
            debug_log_values=False,
        ),
        intents={
            "SI": [
                "si",
                "transfierame",
                "quiero hablar con un representante",
            ],
            "NO": [
                "no",
                "no me transfiera",
                "no quiero",
            ],
            "DUDA": [
                "quien habla",
                "no entiendo",
                "no se",
            ],
            "SILENCIO": [],
            "INFO_COBRO": [
                "quiero saber que me estan cobrando",
                "cuanto debo",
                "de que es esa deuda",
            ],
        },
    )


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.NullHandler())
    return logger


def build_agi_session() -> tuple[AgiSession, StringIO]:
    stdin = StringIO("200 result=1\n" * 20)
    stdout = StringIO()
    return AgiSession(stdin=stdin, stdout=stdout), stdout


def extract_agi_commands(stdout: StringIO) -> list[str]:
    return [line for line in stdout.getvalue().splitlines() if line]


def assert_required_set_variable_commands(commands: list[str]) -> None:
    set_commands = [command for command in commands if command.startswith("SET VARIABLE ")]
    assert set_commands[0].startswith('SET VARIABLE VOSK_TEXT "')
    assert set_commands[1].startswith('SET VARIABLE VOSK_INTENT "')
    assert set_commands[2].startswith('SET VARIABLE VOSK_CONFIDENCE "')
    assert set_commands[3].startswith('SET VARIABLE VOSK_SOURCE "')
    assert set_commands[4].startswith('SET VARIABLE VOSK_DECISION "')
    assert set_commands[5].startswith('SET VARIABLE VOSK_TRANSFER_ELIGIBLE "')
    assert set_commands[6].startswith('SET VARIABLE VOSK_BLOCK_REASON "')
    assert set_commands[7].startswith('SET VARIABLE VOSK_FINAL_DISPOSITION "')
    assert set_commands[8].startswith('SET VARIABLE VOSK_MATCHED_VALUE "')


def test_lab_integration_sets_si_from_partial_audio(monkeypatch) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "si"}),
            json.dumps({"partial": "si"}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    config = build_config()
    logger = build_logger("test_lab_integration.si")
    service = build_service(config=config, logger=logger)
    session, stdout = build_agi_session()

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\x01\x02" * 4000,
        environment={
            "agi_channel": "SIP/lab-1001",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.111",
        },
    )

    commands = extract_agi_commands(stdout)

    assert result == 0
    assert websocket.sent_binary
    assert websocket.closed is True
    assert_required_set_variable_commands(commands)
    assert 'SET VARIABLE VOSK_TEXT "si"' in commands
    assert 'SET VARIABLE VOSK_INTENT "SI"' in commands
    assert 'SET VARIABLE VOSK_CONFIDENCE "1.00"' in commands
    assert 'SET VARIABLE VOSK_SOURCE "transcript"' in commands
    assert 'SET VARIABLE VOSK_DECISION "TRANSFER"' in commands


def test_lab_integration_sets_no_from_negative_partial(monkeypatch) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "no me transfiera"}),
            json.dumps({"partial": "no me transfiera"}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    config = build_config()
    logger = build_logger("test_lab_integration.no")
    service = build_service(config=config, logger=logger)
    session, stdout = build_agi_session()

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\x01\x02" * 4000,
        environment={
            "agi_channel": "SIP/lab-1001",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.112",
        },
    )

    commands = extract_agi_commands(stdout)

    assert result == 0
    assert_required_set_variable_commands(commands)
    assert 'SET VARIABLE VOSK_TEXT "no me transfiera"' in commands
    assert 'SET VARIABLE VOSK_INTENT "NO"' in commands
    assert 'SET VARIABLE VOSK_SOURCE "transcript"' in commands
    assert 'SET VARIABLE VOSK_DECISION "NO_TRANSFER"' in commands


def test_lab_integration_sets_silencio_when_audio_is_empty() -> None:
    config = build_config()
    logger = build_logger("test_lab_integration.silence")
    service = build_service(config=config, logger=logger)
    session, stdout = build_agi_session()

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"",
        environment={
            "agi_channel": "SIP/lab-1001",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.113",
        },
    )

    commands = extract_agi_commands(stdout)

    assert result == 0
    assert_required_set_variable_commands(commands)
    assert 'SET VARIABLE VOSK_TEXT ""' in commands
    assert 'SET VARIABLE VOSK_INTENT "SILENCIO"' in commands
    assert 'SET VARIABLE VOSK_CONFIDENCE "0.00"' in commands
    assert 'SET VARIABLE VOSK_DECISION "RETRY"' in commands


def test_lab_integration_sets_info_cobro_from_informational_phrase(monkeypatch) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "quiero saber que me estan cobrando"}),
            json.dumps({"partial": "quiero saber que me estan cobrando"}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    config = build_config()
    logger = build_logger("test_lab_integration.info_cobro")
    service = build_service(config=config, logger=logger)
    session, stdout = build_agi_session()

    result = run_eagi_session(
        session=session,
        service=service,
        config=config,
        logger=logger,
        capture_audio=lambda fd, listen_seconds, sample_rate: b"\x01\x02" * 4000,
        environment={
            "agi_channel": "SIP/lab-1001",
            "agi_callerid": "3001234567",
            "agi_uniqueid": "1716123456.114",
        },
    )

    commands = extract_agi_commands(stdout)

    assert result == 0
    assert_required_set_variable_commands(commands)
    assert 'SET VARIABLE VOSK_TEXT "quiero saber que me estan cobrando"' in commands
    assert any(
        command == 'SET VARIABLE VOSK_INTENT "INFO_COBRO"'
        or command == 'SET VARIABLE VOSK_INTENT "SI"'
        for command in commands
    )
