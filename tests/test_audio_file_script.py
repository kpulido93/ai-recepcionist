from __future__ import annotations

import importlib.util
import json
import sys
import wave
from pathlib import Path

from websocket import WebSocketConnectionClosedException

from vicidial_vosk_cobranza_ivr import vosk_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "test_audio_file.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

agi_vosk_cobranza = importlib.import_module("agi.vosk_cobranza")

_SPEC = importlib.util.spec_from_file_location("scripts_test_audio_file", SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
test_audio_file = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(test_audio_file)


class FakeWebSocket:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.sent_messages: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        self.sent_messages.append(payload)

    def settimeout(self, timeout: float) -> None:
        return None

    def recv(self) -> object:
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def _write_test_wav(path: Path, audio_bytes: bytes, sample_rate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_bytes)


def test_script_uses_agi_sender_and_handles_partial_close(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    audio_bytes = b"\xff\x7f" * 400
    wav_path = tmp_path / "partial.wav"
    _write_test_wav(wav_path, audio_bytes)

    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": "quiero saber que me estan cobrando"}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )
    sent_chunks: list[bytes] = []
    connection_args: dict[str, object] = {}

    def fake_create_connection(url: str, timeout: float) -> FakeWebSocket:
        connection_args["url"] = url
        connection_args["timeout"] = timeout
        return websocket

    def fake_send_audio_to_vosk(_websocket: object, chunk: bytes) -> None:
        sent_chunks.append(chunk)

    monkeypatch.setattr(vosk_client, "create_connection", fake_create_connection)
    monkeypatch.setattr(agi_vosk_cobranza, "send_audio_to_vosk", fake_send_audio_to_vosk)

    exit_code = test_audio_file.main(
        [
            str(wav_path),
            "--vosk-url",
            "ws://test-vosk:2700",
            "--sample-rate",
            "16000",
            "--show-partials",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert connection_args["url"] == "ws://test-vosk:2700"
    assert sent_chunks == [audio_bytes]
    assert "sample_rate: 16000" in captured.out
    assert "text: quiero saber que me estan cobrando" in captured.out
    assert "intent: INFO_COBRO" in captured.out
    assert 'partials: ["quiero saber que me estan cobrando"]' in captured.out
    assert "WARN: --sample-rate sobreescribe el header WAV" in captured.err
    assert websocket.closed is True


def test_script_treats_empty_vosk_result_as_silencio(monkeypatch, tmp_path: Path, capsys) -> None:
    audio_bytes = b"\xff\x7f" * 400
    wav_path = tmp_path / "silencio.wav"
    _write_test_wav(wav_path, audio_bytes)

    websocket = FakeWebSocket(
        responses=[
            json.dumps({"partial": ""}),
            WebSocketConnectionClosedException("closed after eof"),
        ]
    )

    monkeypatch.setattr(vosk_client, "create_connection", lambda _url, timeout: websocket)
    monkeypatch.setattr(agi_vosk_cobranza, "send_audio_to_vosk", lambda _ws, _chunk: None)

    exit_code = test_audio_file.main([str(wav_path)])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "text: " in captured.out
    assert "intent: SILENCIO" in captured.out
    assert "confidence: 0.00" in captured.out
    assert "source: silence" in captured.out
    assert websocket.closed is True
