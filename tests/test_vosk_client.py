from __future__ import annotations

import json
import logging

import pytest
from websocket import ABNF, WebSocketConnectionClosedException

from vicidial_vosk_cobranza_ivr import vosk_client
from vicidial_vosk_cobranza_ivr.intent_classifier import detect_early_intent
from vicidial_vosk_cobranza_ivr.vosk_client import (
    VoskClient,
    VoskProtocolError,
    VoskTimeoutError,
    _receive_vosk_message,
    send_audio_to_vosk,
)

EARLY_INTENTS_CONFIG = {
    "SI": [
        "si",
        "transfierame",
        "quiero hablar",
        "comuniqueme",
    ],
    "INFO_COBRO": [
        "quiero saber que me estan cobrando",
        "cuanto debo",
    ],
    "PROMESA_PAGO": [
        "quiero pagar",
        "quiero resolver",
    ],
    "NO": [
        "no",
        "no quiero",
        "no me transfiera",
    ],
    "NUMERO_EQUIVOCADO": [
        "numero equivocado",
        "aqui no vive",
    ],
    "NO_ES_PERSONA": [
        "no soy esa persona",
    ],
    "CALLBACK": [
        "llameme despues",
    ],
    "DUDA": [
        "quien habla",
        "no entiendo",
    ],
    "SILENCIO": [],
}


def detect_test_early_intent(partial: str):
    return detect_early_intent(partial, intents_config=EARLY_INTENTS_CONFIG)


class FakeWebSocket:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.sent_messages: list[str] = []
        self.sent_binary: list[bytes] = []
        self.sent_opcodes: list[int | None] = []
        self.timeouts: list[float] = []
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
        self.timeouts.append(timeout)

    def recv(self) -> object:
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def test_vosk_client_transcribes_pcm_over_websocket(monkeypatch) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"text": "si", "result": [{"conf": 0.8}]}),
            json.dumps({"text": "si", "result": [{"conf": 1.0}]}),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)
    result = client.transcribe_pcm(audio_bytes=b"\x01\x02" * 1000, sample_rate=8000)

    assert result.transcript == "si"
    assert result.confidence == 0.9
    assert websocket.sent_messages[0] == json.dumps({"config": {"sample_rate": 8000}})
    assert websocket.sent_messages[-1] == json.dumps({"eof": 1})
    assert websocket.sent_binary
    assert websocket.closed is True


def test_receive_vosk_message_ignores_empty_frames_then_parses_json() -> None:
    websocket = FakeWebSocket(
        responses=[
            None,
            "",
            "   ",
            json.dumps({"partial": "hola"}),
        ]
    )

    response = _receive_vosk_message(websocket, deadline=10**9)

    assert response == {"partial": "hola"}


def test_send_audio_to_vosk_uses_binary_opcode() -> None:
    websocket = FakeWebSocket(responses=[])

    send_audio_to_vosk(websocket, b"\x01\x02\x03")

    assert websocket.sent_binary == [b"\x01\x02\x03"]
    assert websocket.sent_opcodes == [ABNF.OPCODE_BINARY]


def test_vosk_client_raises_timeout_error(monkeypatch) -> None:
    websocket = FakeWebSocket(responses=[TimeoutError("slow")])
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)

    with pytest.raises(VoskTimeoutError, match="ws://127.0.0.1:2700"):
        client.transcribe_pcm(audio_bytes=b"\x01\x02" * 1000, sample_rate=8000)

    assert websocket.closed is True


def test_vosk_client_returns_last_partial_when_socket_closes_after_eof(
    monkeypatch,
    caplog,
) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "quiero saber que me estan cobrando"}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)
    caplog.set_level(logging.DEBUG, logger="vicidial_vosk_cobranza_ivr.vosk_client")

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)
    result = client.transcribe_pcm(audio_bytes=b"\x01\x02" * 1000, sample_rate=8000)

    assert result.transcript == "quiero saber que me estan cobrando"
    assert result.confidence is None
    assert websocket.closed is True
    assert any("cierre tolerado" in record.message for record in caplog.records)
    assert any("partials_relevantes" in record.message for record in caplog.records)


def test_vosk_client_returns_empty_text_when_socket_closes_after_eof_without_results(
    monkeypatch,
) -> None:
    websocket = FakeWebSocket(
        responses=[
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)
    result = client.transcribe_pcm(audio_bytes=b"", sample_rate=8000)

    assert result.transcript == ""
    assert result.confidence is None
    assert websocket.closed is True


def test_vosk_client_rejects_invalid_json(monkeypatch) -> None:
    websocket = FakeWebSocket(responses=["{not-json"])
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)

    with pytest.raises(VoskProtocolError):
        client.transcribe_pcm(audio_bytes=b"\x01\x02" * 1000, sample_rate=8000)

    assert websocket.closed is True


def test_vosk_client_rejects_unexpected_binary_frame(monkeypatch) -> None:
    websocket = FakeWebSocket(responses=[b"\x00\x01"])
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(websocket_url="ws://127.0.0.1:2700", timeout_seconds=10)

    with pytest.raises(VoskProtocolError):
        client.transcribe_pcm(audio_bytes=b"\x01\x02" * 1000, sample_rate=8000)

    assert websocket.closed is True


@pytest.mark.parametrize(
    ("partial", "expected_intent", "expected_transcript"),
    [
        ("si", "SI", "si"),
        ("si transfierame", "SI", "si transfierame"),
        (
            "quiero saber que me estan cobrando",
            "INFO_COBRO",
            "quiero saber que me estan cobrando",
        ),
        ("quiero pagar", "PROMESA_PAGO", "quiero pagar"),
        ("no me transfiera", "NO", "no me transfiera"),
        ("numero equivocado", "NUMERO_EQUIVOCADO", "numero equivocado"),
    ],
)
def test_vosk_client_uses_early_intent_and_ignores_late_noise(
    monkeypatch,
    partial: str,
    expected_intent: str,
    expected_transcript: str,
) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": partial}),
            json.dumps({"partial": partial}),
            json.dumps({"text": "es decir flip", "result": [{"conf": 0.2}]}),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(
        websocket_url="ws://127.0.0.1:2700",
        timeout_seconds=10,
        early_detection_enabled=True,
        early_detection_min_audio_ms=250,
        early_detection_min_chars=2,
        early_intent_detector=detect_test_early_intent,
    )
    result = client.transcribe_pcm(audio_bytes=b"\x01\x02" * 3200, sample_rate=8000)

    assert result.transcript == expected_transcript
    assert result.early_intent == expected_intent
    assert result.early_matched_phrase is not None
    assert result.finish_reason == "early_intent"
    assert websocket.closed is True


def test_vosk_client_does_not_trigger_early_intent_on_false_positive_partial(monkeypatch) -> None:
    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "silla"}),
            json.dumps({"text": "silla", "result": [{"conf": 0.4}]}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)

    client = VoskClient(
        websocket_url="ws://127.0.0.1:2700",
        timeout_seconds=10,
        early_detection_enabled=True,
        early_detection_min_audio_ms=250,
        early_detection_min_chars=2,
        early_intent_detector=detect_test_early_intent,
    )
    result = client.transcribe_pcm(audio_bytes=b"\x01\x02" * 3200, sample_rate=8000)

    assert result.transcript == "silla"
    assert result.early_intent is None
    assert result.finish_reason == "eof"
    assert websocket.closed is True
