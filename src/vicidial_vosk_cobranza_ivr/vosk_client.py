from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from websocket import (
    ABNF,
    WebSocketConnectionClosedException,
    WebSocketException,
    create_connection,
)

from vicidial_vosk_cobranza_ivr.intent_classifier import intent_value


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
    early_intent: str | None = None
    early_matched_phrase: str | None = None
    finish_reason: str = "eof"


LOGGER = logging.getLogger(__name__)
MAX_EMPTY_FRAMES = 5


class VoskClient:
    def __init__(
        self,
        websocket_url: str,
        timeout_seconds: int = 10,
        audio_sender: Callable[[Any, bytes], None] | None = None,
        early_detection_enabled: bool = False,
        early_detection_min_audio_ms: int = 250,
        early_detection_min_chars: int = 2,
        early_intent_detector: Callable[[str], Any] | None = None,
    ) -> None:
        self.websocket_url = websocket_url
        self.timeout_seconds = timeout_seconds
        self.audio_sender = audio_sender or send_audio_to_vosk
        self.early_detection_enabled = early_detection_enabled
        self.early_detection_min_audio_ms = early_detection_min_audio_ms
        self.early_detection_min_chars = early_detection_min_chars
        self.early_intent_detector = early_intent_detector

    def transcribe_pcm(self, audio_bytes: bytes, sample_rate: int) -> RecognitionResult:
        messages: list[dict[str, Any]] = []
        transcript = ""
        last_partial = ""
        partial_count = 0
        finish_reason = "eof"
        eof_connection_closed = False
        websocket = None
        chunk_size = max(1600, int(sample_rate * 2 * 0.2))
        confidences: list[float] = []
        bytes_sent = 0
        deadline = time.monotonic() + self.timeout_seconds

        try:
            LOGGER.debug(
                "Abriendo websocket Vosk websocket_url=%s sample_rate=%s",
                self.websocket_url,
                sample_rate,
            )
            websocket = create_connection(
                self.websocket_url,
                timeout=_remaining_time(deadline),
            )
            websocket.send(json.dumps({"config": {"sample_rate": sample_rate}}))

            for offset in range(0, len(audio_bytes), chunk_size):
                _ensure_deadline(deadline)
                chunk = audio_bytes[offset : offset + chunk_size]
                self.audio_sender(websocket, chunk)
                bytes_sent += len(chunk)
                response = _receive_vosk_message(websocket, deadline)
                if response is None:
                    raise VoskProtocolError(
                        "Vosk cerro la conexion sin responder durante el envio."
                    )
                messages.append(response)
                confidences.extend(_extract_confidences(response))
                transcript, last_partial, partial_count = _update_transcript_state(
                    response=response,
                    transcript=transcript,
                    last_partial=last_partial,
                    partial_count=partial_count,
                )
                early_match = self._detect_early_intent(
                    partial=last_partial,
                    bytes_sent=bytes_sent,
                    sample_rate=sample_rate,
                )
                if early_match is not None:
                    finish_reason = "early_intent"
                    LOGGER.info(
                        "early_intent=true intent=%s matched_phrase=%s partial=%s",
                        intent_value(early_match.intent),
                        early_match.matched_value,
                        early_match.transcript,
                    )
                    _ensure_deadline(deadline)
                    websocket.send(json.dumps({"eof": 1}))
                    final_response = _receive_vosk_message(
                        websocket,
                        deadline,
                        allow_connection_close=True,
                    )
                    if final_response is not None:
                        messages.append(final_response)
                        confidences.extend(_extract_confidences(final_response))
                    else:
                        eof_connection_closed = True
                    return self._build_result(
                        transcript=early_match.transcript,
                        raw_messages=messages,
                        confidence=early_match.confidence,
                        sample_rate=sample_rate,
                        bytes_sent=bytes_sent,
                        partial_count=partial_count,
                        finish_reason=finish_reason,
                        early_intent=intent_value(early_match.intent),
                        early_matched_phrase=early_match.matched_value,
                        eof_connection_closed=eof_connection_closed,
                    )

            _ensure_deadline(deadline)
            websocket.send(json.dumps({"eof": 1}))
            final_response = _receive_vosk_message(
                websocket,
                deadline,
                allow_connection_close=True,
            )
            if final_response is not None:
                messages.append(final_response)
                confidences.extend(_extract_confidences(final_response))
                transcript, last_partial, partial_count = _update_transcript_state(
                    response=final_response,
                    transcript=transcript,
                    last_partial=last_partial,
                    partial_count=partial_count,
                )
            else:
                eof_connection_closed = True

            final_text = transcript or last_partial

            confidence = None
            if final_text:
                confidence = sum(confidences) / len(confidences) if confidences else None

            return self._build_result(
                transcript=final_text,
                raw_messages=messages,
                confidence=confidence,
                sample_rate=sample_rate,
                bytes_sent=bytes_sent,
                partial_count=partial_count,
                finish_reason=finish_reason,
                eof_connection_closed=eof_connection_closed,
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

    def _build_result(
        self,
        *,
        transcript: str,
        raw_messages: list[dict[str, Any]],
        confidence: float | None,
        sample_rate: int,
        bytes_sent: int,
        partial_count: int,
        finish_reason: str,
        early_intent: str | None = None,
        early_matched_phrase: str | None = None,
        eof_connection_closed: bool = False,
    ) -> RecognitionResult:
        relevant_partials = _extract_relevant_partials(raw_messages)
        LOGGER.debug(
            (
                "Vosk websocket_url=%s sample_rate=%s bytes_enviados=%s partials=%s "
                "partials_relevantes=%s early_intent=%s matched_phrase=%s texto_final=%s "
                "finish_reason=%s cierre_eof_tolerado=%s"
            ),
            self.websocket_url,
            sample_rate,
            bytes_sent,
            partial_count,
            relevant_partials,
            early_intent,
            early_matched_phrase,
            transcript,
            finish_reason,
            eof_connection_closed,
        )
        return RecognitionResult(
            transcript=transcript,
            raw_messages=raw_messages,
            confidence=confidence,
            early_intent=early_intent,
            early_matched_phrase=early_matched_phrase,
            finish_reason=finish_reason,
        )

    def _detect_early_intent(
        self,
        *,
        partial: str,
        bytes_sent: int,
        sample_rate: int,
    ) -> Any | None:
        if not self.early_detection_enabled or self.early_intent_detector is None:
            return None
        if len(partial) < self.early_detection_min_chars:
            return None
        if _bytes_to_audio_ms(bytes_sent, sample_rate) < self.early_detection_min_audio_ms:
            return None
        return self.early_intent_detector(partial)


def send_audio_to_vosk(websocket: Any, audio_chunk: bytes) -> None:
    websocket.send(audio_chunk, opcode=ABNF.OPCODE_BINARY)


def _receive_vosk_message(
    websocket: Any,
    deadline: float,
    *,
    allow_connection_close: bool = False,
    max_empty_frames: int = MAX_EMPTY_FRAMES,
) -> dict[str, Any] | None:
    empty_frames = 0
    while True:
        websocket.settimeout(_remaining_time(deadline))
        try:
            payload = websocket.recv()
        except WebSocketConnectionClosedException:
            if allow_connection_close:
                LOGGER.debug("Vosk cerro la conexion tras EOF; cierre tolerado.")
                return None
            raise VoskConnectionError(
                "Vosk cerro la conexion antes de devolver un resultado."
            ) from None

        if payload is None:
            empty_frames += 1
            if empty_frames > max_empty_frames:
                raise VoskProtocolError("Vosk devolvio demasiados frames vacios.")
            continue

        if isinstance(payload, bytes):
            if not payload.strip():
                empty_frames += 1
                if empty_frames > max_empty_frames:
                    raise VoskProtocolError("Vosk devolvio demasiados frames vacios.")
                continue
            raise VoskProtocolError("Vosk devolvio un frame binario inesperado.")

        if not isinstance(payload, str):
            raise VoskProtocolError("Vosk devolvio un frame con tipo inesperado.")

        if not payload.strip():
            empty_frames += 1
            if empty_frames > max_empty_frames:
                raise VoskProtocolError("Vosk devolvio demasiados frames vacios.")
            continue

        try:
            response = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise VoskProtocolError("Respuesta JSON invalida de Vosk.") from exc
        if not isinstance(response, dict):
            raise VoskProtocolError("Respuesta JSON invalida de Vosk.")
        return response


def _update_transcript_state(
    *,
    response: dict[str, Any],
    transcript: str,
    last_partial: str,
    partial_count: int,
) -> tuple[str, str, int]:
    next_transcript = transcript
    next_partial = last_partial
    next_partial_count = partial_count

    text_value = str(response.get("text", "")).strip()
    if text_value:
        next_transcript = text_value

    partial_value = str(response.get("partial", "")).strip()
    if partial_value:
        next_partial = partial_value
        next_partial_count += 1

    return next_transcript, next_partial, next_partial_count


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


def _extract_relevant_partials(
    raw_messages: Sequence[dict[str, Any]],
    limit: int = 3,
) -> list[str]:
    partials: list[str] = []
    for message in raw_messages:
        partial = str(message.get("partial", "")).strip()
        if partial:
            partials.append(partial)
    if limit <= 0:
        return []
    return partials[-limit:]


def _ensure_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise VoskTimeoutError("La transaccion con Vosk excedio el deadline global.")


def _remaining_time(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VoskTimeoutError("La transaccion con Vosk excedio el deadline global.")
    return remaining


def _bytes_to_audio_ms(audio_bytes_length: int, sample_rate: int) -> int:
    if sample_rate <= 0:
        return 0
    return int((audio_bytes_length / (sample_rate * 2)) * 1000)
