from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from websocket import WebSocketException, create_connection


class VoskConnectionError(RuntimeError):
    """Raised when the local Vosk server cannot be reached or parsed."""


@dataclass(frozen=True)
class RecognitionResult:
    transcript: str
    raw_messages: list[dict[str, Any]]


class VoskClient:
    def __init__(self, websocket_url: str, timeout_seconds: int = 10) -> None:
        self.websocket_url = websocket_url
        self.timeout_seconds = timeout_seconds

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int) -> RecognitionResult:
        messages: list[dict[str, Any]] = []
        transcript = ""
        websocket = None
        chunk_size = max(1600, int(sample_rate * 2 * 0.2))

        try:
            websocket = create_connection(self.websocket_url, timeout=self.timeout_seconds)
            websocket.send(json.dumps({"config": {"sample_rate": sample_rate}}))

            for offset in range(0, len(audio_bytes), chunk_size):
                websocket.send_binary(audio_bytes[offset : offset + chunk_size])
                response = _receive_message(websocket)
                if response:
                    messages.append(response)
                    transcript = str(response.get("text", transcript)).strip()

            websocket.send(json.dumps({"eof": 1}))
            final_response = _receive_message(websocket)
            if final_response:
                messages.append(final_response)
                transcript = str(final_response.get("text", transcript)).strip()

            return RecognitionResult(transcript=transcript, raw_messages=messages)
        except (OSError, WebSocketException, TimeoutError, ValueError) as exc:
            message = f"No fue posible consultar Vosk en {self.websocket_url}"
            raise VoskConnectionError(message) from exc
        finally:
            if websocket is not None:
                websocket.close()


def _receive_message(websocket: Any) -> dict[str, Any]:
    payload = websocket.recv()
    if isinstance(payload, bytes):
        raise ValueError("Vosk devolvio un frame binario inesperado.")
    response = json.loads(payload)
    if not isinstance(response, dict):
        raise ValueError("Respuesta JSON invalida de Vosk.")
    return response
