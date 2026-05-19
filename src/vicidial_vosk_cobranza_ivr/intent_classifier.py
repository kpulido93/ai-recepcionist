from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml


class Intent(str, Enum):
    SI = "SI"
    NO = "NO"
    DUDA = "DUDA"
    SILENCIO = "SILENCIO"


@dataclass(frozen=True)
class IntentClassification:
    intent: Intent
    transcript: str
    matched_value: str | None
    source: str
    confidence: float


@dataclass(frozen=True)
class PhraseMatch:
    intent: Intent
    phrase: str
    score: float


class IntentClassifier:
    def __init__(
        self,
        phrases: Mapping[str, Sequence[str]],
        default_intent: str,
        dtmf_map: Mapping[str, str],
    ) -> None:
        self.default_intent = Intent(default_intent)
        self.dtmf_map = {digit: Intent(intent_name) for digit, intent_name in dtmf_map.items()}
        self.phrases = {
            Intent(intent_name): [normalize_text(phrase) for phrase in phrase_list]
            for intent_name, phrase_list in phrases.items()
            if intent_name in Intent.__members__
        }

    @classmethod
    def from_yaml(
        cls,
        intents_path: Path,
        default_intent: str = "DUDA",
        dtmf_map: Mapping[str, str] | None = None,
    ) -> IntentClassifier:
        return cls(
            phrases=load_intents(intents_path),
            default_intent=default_intent,
            dtmf_map=dtmf_map or {},
        )

    def classify(
        self,
        transcript: str | None = None,
        dtmf: str | None = None,
    ) -> IntentClassification:
        dtmf_classification = self.classify_dtmf(dtmf)
        if dtmf_classification is not None:
            return dtmf_classification

        normalized_text = normalize_text(transcript or "")
        if not normalized_text:
            return IntentClassification(
                intent=Intent.SILENCIO,
                transcript="",
                matched_value=None,
                source="silence",
                confidence=0.0,
            )

        yes_match = self._find_best_match(normalized_text, Intent.SI)
        no_match = self._find_best_match(normalized_text, Intent.NO)
        doubt_match = self._find_best_match(normalized_text, Intent.DUDA)

        strongest_yes_no = max(
            yes_match.score if yes_match is not None else 0.0,
            no_match.score if no_match is not None else 0.0,
        )

        if doubt_match is not None and doubt_match.score >= strongest_yes_no:
            return IntentClassification(
                intent=doubt_match.intent,
                transcript=transcript or "",
                matched_value=doubt_match.phrase,
                source="transcript",
                confidence=doubt_match.score,
            )

        if yes_match and no_match:
            return IntentClassification(
                intent=Intent.DUDA,
                transcript=transcript or "",
                matched_value=f"{yes_match.phrase}|{no_match.phrase}",
                source="conflict",
                confidence=round(min(yes_match.score, no_match.score) * 0.5, 2),
            )

        if yes_match:
            return IntentClassification(
                intent=yes_match.intent,
                transcript=transcript or "",
                matched_value=yes_match.phrase,
                source="transcript",
                confidence=yes_match.score,
            )

        if no_match:
            return IntentClassification(
                intent=no_match.intent,
                transcript=transcript or "",
                matched_value=no_match.phrase,
                source="transcript",
                confidence=no_match.score,
            )

        return IntentClassification(
            intent=self.default_intent,
            transcript=transcript or "",
            matched_value=None,
            source="default",
            confidence=0.35,
        )

    def classify_dtmf(self, dtmf: str | None) -> IntentClassification | None:
        if not dtmf:
            return None

        normalized_dtmf = dtmf.strip()
        if normalized_dtmf not in self.dtmf_map:
            return None

        return IntentClassification(
            intent=self.dtmf_map[normalized_dtmf],
            transcript="",
            matched_value=normalized_dtmf,
            source="dtmf",
            confidence=1.0,
        )

    def _find_best_match(self, normalized_text: str, intent: Intent) -> PhraseMatch | None:
        best_match: PhraseMatch | None = None
        for phrase in self.phrases.get(intent, []):
            score = _match_score(normalized_text, phrase)
            if score <= 0:
                continue

            candidate = PhraseMatch(intent=intent, phrase=phrase, score=score)
            if best_match is None:
                best_match = candidate
                continue

            if candidate.score > best_match.score:
                best_match = candidate
                continue

            if candidate.score == best_match.score and len(candidate.phrase) > len(
                best_match.phrase
            ):
                best_match = candidate

        return best_match


def load_intents(path: Path) -> dict[str, list[str]]:
    with path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"El archivo de intents debe tener un objeto en la raiz: {path}")

    normalized_phrases: dict[str, list[str]] = {}
    for intent_name in Intent.__members__:
        raw_phrases = loaded.get(intent_name, [])
        if not isinstance(raw_phrases, list):
            raise ValueError(f"El intent {intent_name} debe contener una lista.")

        normalized_phrases[intent_name] = [
            normalize_text(str(phrase)) for phrase in raw_phrases if normalize_text(str(phrase))
        ]

    return normalized_phrases


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    without_punctuation = re.sub(r"[^a-z0-9\s]", " ", ascii_only)
    collapsed = re.sub(r"\s+", " ", without_punctuation).strip()
    return collapsed


def _match_score(normalized_text: str, phrase: str) -> float:
    if not phrase:
        return 0.0

    if normalized_text == phrase:
        return 1.0

    haystack = f" {normalized_text} "
    needle = f" {phrase} "
    if needle in haystack:
        token_bonus = min(0.1, len(phrase.split()) * 0.03)
        return round(0.8 + token_bonus, 2)

    return 0.0
