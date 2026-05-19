from __future__ import annotations

import logging
from dataclasses import dataclass

from vicidial_vosk_cobranza_ivr.config import AppConfig
from vicidial_vosk_cobranza_ivr.intent_classifier import (
    Intent,
    IntentClassification,
    IntentClassifier,
)
from vicidial_vosk_cobranza_ivr.vosk_client import VoskClient, VoskConnectionError


@dataclass(frozen=True)
class ProcessingOutcome:
    intent: Intent
    transcript: str
    source: str
    dtmf: str | None = None


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
        if dtmf:
            classification = self.classifier.classify(dtmf=dtmf)
            return _build_outcome(classification, dtmf=dtmf)

        if not audio_bytes:
            classification = self.classifier.classify(transcript="")
            return _build_outcome(classification)

        try:
            recognition = self.vosk_client.transcribe_pcm(audio_bytes, sample_rate)
        except VoskConnectionError as exc:
            self.logger.warning("Fallo Vosk, usando default_intent: %s", exc)
            return ProcessingOutcome(
                intent=Intent(self.config.ivr.default_intent),
                transcript="",
                source="vosk_error",
                dtmf=None,
            )

        classification = self.classifier.classify(transcript=recognition.transcript)
        return _build_outcome(classification)


def _build_outcome(
    classification: IntentClassification,
    dtmf: str | None = None,
) -> ProcessingOutcome:
    return ProcessingOutcome(
        intent=classification.intent,
        transcript=classification.transcript,
        source=classification.source,
        dtmf=dtmf,
    )
