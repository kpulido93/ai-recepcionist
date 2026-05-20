from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from vicidial_vosk_cobranza_ivr.audio import calculate_rms
from vicidial_vosk_cobranza_ivr.config import AppConfig
from vicidial_vosk_cobranza_ivr.intent_classifier import (
    Intent,
    IntentClassification,
    IntentClassifier,
    IntentName,
    intent_equals,
    normalize_text,
    resolve_intent_name,
)
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient, VoskError


@dataclass(frozen=True)
class ProcessingOutcome:
    intent: IntentName
    transcript: str
    source: str
    confidence: float
    finish_reason: str
    matched_value: str | None = None
    dtmf: str | None = None
    raw_messages: tuple[dict[str, Any], ...] = ()


class CobranzaIvrService:
    def __init__(
        self,
        config: AppConfig,
        classifier: IntentClassifier,
        vosk_client: VoskClient,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.classifier = classifier
        self.vosk_client = vosk_client
        self.logger = logger

    def classify_audio_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        dtmf: str | None = None,
    ) -> ProcessingOutcome:
        dtmf_classification = self.classifier.classify_dtmf(dtmf)
        if dtmf_classification is not None:
            return _build_outcome(
                classification=dtmf_classification,
                source="dtmf",
                confidence=dtmf_classification.confidence,
                finish_reason="dtmf",
                dtmf=dtmf,
            )

        audio_rms = calculate_rms(audio_bytes)
        if not audio_bytes or audio_rms < self.config.audio.min_rms:
            return ProcessingOutcome(
                intent=Intent.SILENCIO,
                transcript="",
                source="silence",
                confidence=0.0,
                finish_reason="no_audio",
                matched_value=None,
                dtmf=None,
                raw_messages=(),
            )

        try:
            recognition = self.vosk_client.transcribe_pcm(audio_bytes, sample_rate)
        except VoskError as exc:
            self.logger.warning("Fallo Vosk, usando source=error: %s", exc)
            return ProcessingOutcome(
                intent=resolve_intent_name(self.config.ivr.default_intent),
                transcript="",
                source="error",
                confidence=0.0,
                finish_reason="error",
                matched_value=None,
                dtmf=None,
                raw_messages=(),
            )

        if recognition.early_intent:
            early_intent = resolve_intent_name(recognition.early_intent)
            transcript = normalize_text(recognition.transcript)
            confidence = recognition.confidence if recognition.confidence is not None else 0.9
            return _build_outcome(
                classification=IntentClassification(
                    intent=early_intent,
                    transcript=transcript,
                    matched_value=recognition.early_matched_phrase,
                    source="early_detection",
                    confidence=confidence,
                ),
                source="speech",
                confidence=confidence,
                finish_reason=recognition.finish_reason,
                raw_messages=tuple(recognition.raw_messages),
            )

        classification = self.classifier.classify(transcript=recognition.transcript)
        source = "silence" if intent_equals(classification.intent, Intent.SILENCIO) else "speech"
        confidence = _resolve_confidence(
            classifier_confidence=classification.confidence,
            recognition_confidence=recognition.confidence,
            source=source,
        )
        transcript = "" if source == "silence" else normalize_text(recognition.transcript)
        return _build_outcome(
            classification=IntentClassification(
                intent=classification.intent,
                transcript=transcript,
                matched_value=classification.matched_value,
                source=classification.source,
                confidence=classification.confidence,
            ),
            source=source,
            confidence=confidence,
            finish_reason=recognition.finish_reason,
            raw_messages=tuple(recognition.raw_messages),
        )


def _build_outcome(
    classification: IntentClassification,
    source: str,
    confidence: float,
    finish_reason: str,
    dtmf: str | None = None,
    raw_messages: tuple[dict[str, Any], ...] = (),
) -> ProcessingOutcome:
    return ProcessingOutcome(
        intent=classification.intent,
        transcript=classification.transcript,
        source=source,
        confidence=confidence,
        finish_reason=finish_reason,
        matched_value=classification.matched_value,
        dtmf=dtmf,
        raw_messages=raw_messages,
    )


def _resolve_confidence(
    classifier_confidence: float,
    recognition_confidence: float | None,
    source: str,
) -> float:
    if source == "silence":
        return 0.0
    if recognition_confidence is None:
        return classifier_confidence
    return min(classifier_confidence, recognition_confidence)
