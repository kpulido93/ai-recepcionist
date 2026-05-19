from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from websocket import WebSocketException, create_connection


class VoskError(RuntimeError):
    """Raised when the local Vosk interaction fails in a controlled way."""


class VoskTimeoutError(TimeoutError, VoskError):
    """Raised when the complete Vosk transaction exceeds the allowed deadline."""


class VoskConnectionError(VoskError):
    """Raised when the local Vosk server cannot be reached or parsed."""


class VoskProtocolError(VoskError):
    """Raised when Vosk replies with invalid frames or malformed JSON."""


@dataclass(frozen=True)
class RecognitionResult:
    transcript: str
    raw_messages: list[dict[str, Any]]
    confidence: float | None


class VoskClient:
    def __init__(self, websocket_url: str, timeout_seconds: int = 10) -> None:
        self.websocket_url = websocket_url
        self.timeout_seconds = timeout_seconds

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int) -> RecognitionResult:
        messages: list[dict[str, Any]] = []
        transcript = ""
        websocket = None
        chunk_size = max(1600, int(sample_rate * 2 * 0.2))
        confidences: list[float] = []
        deadline = time.monotonic() + self.timeout_seconds

        try:
            websocket = create_connection(
                self.websocket_url,
                timeout=_remaining_time(deadline),
            )
            websocket.send(json.dumps({"config": {"sample_rate": sample_rate}}))

            for offset in range(0, len(audio_bytes), chunk_size):
                _ensure_deadline(deadline)
                websocket.send_binary(audio_bytes[offset : offset + chunk_size])
                response = _receive_message(websocket, deadline)
                if response:
                    messages.append(response)
                    confidences.extend(_extract_confidences(response))
                    transcript = str(response.get("text", transcript)).strip()

            _ensure_deadline(deadline)
            websocket.send(json.dumps({"eof": 1}))
            final_response = _receive_message(websocket, deadline)
            if final_response:
                messages.append(final_response)
                confidences.extend(_extract_confidences(final_response))
                transcript = str(final_response.get("text", transcript)).strip()

            confidence = None
            if transcript:
                confidence = sum(confidences) / len(confidences) if confidences else None

            return RecognitionResult(
                transcript=transcript,
                raw_messages=messages,
                confidence=confidence,
            )
        except VoskError:
            raise
        except TimeoutError as exc:
            message = f"Vosk supero el timeout global en {self.websocket_url}"
            raise VoskTimeoutError(message) from exc
        except (OSError, WebSocketException) as exc:
            message = f"No fue posible consultar Vosk en {self.websocket_url}"
            raise VoskConnectionError(message) from exc
        finally:
            if websocket is not None:
                websocket.close()


def _receive_message(websocket: Any, deadline: float) -> dict[str, Any]:
    websocket.settimeout(_remaining_time(deadline))
    payload = websocket.recv()
    if isinstance(payload, bytes):
        raise VoskProtocolError("Vosk devolvio un frame binario inesperado.")
    try:
        response = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise VoskProtocolError("Respuesta JSON invalida de Vosk.") from exc
    if not isinstance(response, dict):
        raise VoskProtocolError("Respuesta JSON invalida de Vosk.")
    return response


def _extract_confidences(response: dict[str, Any]) -> list[float]:
    confidences: list[float] = []
    result_items = response.get("result", [])
    if not isinstance(result_items, list):
        return confidences

    for item in result_items:
        if not isinstance(item, dict) or "conf" not in item:
            continue

        try:
            confidences.append(float(item["conf"]))
        except (TypeError, ValueError):
            continue

    return confidences


def _ensure_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise VoskTimeoutError("La transaccion con Vosk excedio el deadline global.")


def _remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VoskTimeoutError("La transaccion con Vosk excedio el deadline global.")
    return remaining
