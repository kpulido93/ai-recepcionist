from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from vicidial_vosk_cobranza_ivr.audio import calculate_rms
from vicidial_vosk_cobranza_ivr.config import AppConfig
from vicidial_vosk_cobranza_ivr.decision_engine import DecisionEngine, DecisionOutcome
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
    decision: str = "RETRY"
    transfer_eligible: bool = False
    block_reason: str | None = None
    final_disposition: str = "VOZ_ERROR_CLASIFICACION"
    reason: str = "classification_error"


class CobranzaIvrService:
    def __init__(
        self,
        config: AppConfig,
        classifier: IntentClassifier,
        decision_engine: DecisionEngine,
        vosk_client: VoskClient,
        logger: logging.Logger,
    ) -> None:
        self.config = config
        self.classifier = classifier
        self.decision_engine = decision_engine
        self.vosk_client = vosk_client
        self.logger = logger

    def classify_audio_bytes(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        dtmf: str | None = None,
        retry_count: int = 0,
    ) -> ProcessingOutcome:
        dtmf_classification = self.classifier.classify_dtmf(dtmf)
        if dtmf_classification is not None:
            return _build_outcome(
                classification=dtmf_classification,
                source=dtmf_classification.source,
                confidence=dtmf_classification.confidence,
                finish_reason="dtmf",
                decision=self._decide(dtmf_classification, retry_count=retry_count),
                dtmf=dtmf,
            )

        audio_rms = calculate_rms(audio_bytes)
        if not audio_bytes or audio_rms < self.config.audio.min_rms:
            silence_classification = IntentClassification(
                intent=Intent.SILENCIO,
                transcript="",
                matched_value=None,
                source="silence",
                confidence=0.0,
            )
            silence_decision = self._decide(silence_classification, retry_count=retry_count)
            return ProcessingOutcome(
                intent=silence_classification.intent,
                transcript=silence_classification.transcript,
                source=silence_classification.source,
                confidence=silence_classification.confidence,
                finish_reason="no_audio",
                matched_value=None,
                dtmf=None,
                raw_messages=(),
                decision=silence_decision.decision,
                transfer_eligible=silence_decision.transfer_eligible,
                block_reason=silence_decision.block_reason,
                final_disposition=silence_decision.final_disposition,
                reason=silence_decision.reason,
            )

        try:
            recognition = self.vosk_client.transcribe_pcm(audio_bytes, sample_rate)
        except VoskError as exc:
            self.logger.warning("Fallo Vosk, usando source=error: %s", exc)
            return _build_error_outcome(self.config.ivr.default_intent)

        if recognition.early_intent:
            early_intent = resolve_intent_name(recognition.early_intent)
            transcript = normalize_text(recognition.transcript)
            confidence = recognition.confidence if recognition.confidence is not None else 0.9
            early_classification = IntentClassification(
                intent=early_intent,
                transcript=transcript,
                matched_value=recognition.early_matched_phrase,
                source="transcript",
                confidence=confidence,
            )
            return _build_outcome(
                classification=early_classification,
                source=early_classification.source,
                confidence=confidence,
                finish_reason=recognition.finish_reason,
                decision=self._decide(early_classification, retry_count=retry_count),
                raw_messages=tuple(recognition.raw_messages),
            )

        classification = self.classifier.classify(transcript=recognition.transcript)
        source = (
            "silence"
            if intent_equals(classification.intent, Intent.SILENCIO)
            else classification.source
        )
        confidence = _resolve_confidence(
            classifier_confidence=classification.confidence,
            recognition_confidence=recognition.confidence,
            source=source,
        )
        transcript = "" if source == "silence" else normalize_text(recognition.transcript)
        resolved_classification = IntentClassification(
            intent=classification.intent,
            transcript=transcript,
            matched_value=classification.matched_value,
            source=source,
            confidence=classification.confidence,
        )
        return _build_outcome(
            classification=resolved_classification,
            source=source,
            confidence=confidence,
            finish_reason=recognition.finish_reason,
            decision=self._decide(resolved_classification, retry_count=retry_count),
            raw_messages=tuple(recognition.raw_messages),
        )

    def _decide(
        self,
        classification: IntentClassification,
        *,
        retry_count: int,
    ) -> DecisionOutcome:
        return self.decision_engine.decide(
            intent=classification.intent,
            confidence=classification.confidence,
            transcript=classification.transcript,
            matched_value=classification.matched_value,
            source=classification.source,
            retry_count=retry_count,
        )


def _build_outcome(
    classification: IntentClassification,
    source: str,
    confidence: float,
    finish_reason: str,
    decision: DecisionOutcome,
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
        decision=decision.decision,
        transfer_eligible=decision.transfer_eligible,
        block_reason=decision.block_reason,
        final_disposition=decision.final_disposition,
        reason=decision.reason,
    )


def _build_error_outcome(default_intent: str) -> ProcessingOutcome:
    return ProcessingOutcome(
        intent=resolve_intent_name(default_intent),
        transcript="",
        source="error",
        confidence=0.0,
        finish_reason="error",
        matched_value=None,
        dtmf=None,
        raw_messages=(),
        decision="RETRY",
        transfer_eligible=False,
        block_reason="error",
        final_disposition="VOZ_ERROR_CLASIFICACION",
        reason="classification_error",
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
