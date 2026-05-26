from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

DEFAULT_FUZZY_THRESHOLD = 0.78


@dataclass(frozen=True)
class FuzzyMatchResult:
    intent: str
    matched_value: str
    score: float
    source: str = "fuzzy"
    start_index: int = 0
    end_index: int = 0
    token_count: int = 0


class FuzzyMatcher:
    def __init__(self, threshold: float = DEFAULT_FUZZY_THRESHOLD) -> None:
        self.threshold = max(0.0, min(threshold, 1.0))

    def match(
        self,
        transcript: str,
        intents_config: Mapping[str, Sequence[str]],
    ) -> FuzzyMatchResult | None:
        normalized_text = normalize_text(transcript)
        if not normalized_text:
            return None

        best_match: FuzzyMatchResult | None = None
        for intent_name, phrases in intents_config.items():
            for phrase in phrases:
                candidate = self._match_phrase(
                    normalized_text=normalized_text,
                    intent_name=intent_name,
                    phrase=phrase,
                )
                if candidate is None:
                    continue

                if best_match is None or candidate.score > best_match.score:
                    best_match = candidate
                    continue

                if (
                    candidate.score == best_match.score
                    and candidate.token_count > best_match.token_count
                ):
                    best_match = candidate

        return best_match

    def _match_phrase(
        self,
        *,
        normalized_text: str,
        intent_name: str,
        phrase: str,
    ) -> FuzzyMatchResult | None:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            return None

        tokens = tokenize_text(normalized_text)
        phrase_tokens = tokenize_text(normalized_phrase)
        if not tokens or not phrase_tokens:
            return None

        phrase_length = len(phrase_tokens)
        min_window = max(1, phrase_length - 2)
        max_window = min(len(tokens), phrase_length + 2)

        best_score = 0.0
        best_window: tuple[int, int] | None = None
        for window_size in range(min_window, max_window + 1):
            for start_index in range(len(tokens) - window_size + 1):
                end_index = start_index + window_size
                window_tokens = tokens[start_index:end_index]
                if window_tokens[0] != phrase_tokens[0]:
                    continue
                window_text = " ".join(window_tokens)
                score = round(SequenceMatcher(None, window_text, normalized_phrase).ratio(), 2)
                if score < self.threshold:
                    continue
                if score > best_score:
                    best_score = score
                    best_window = (start_index, end_index)

        if best_window is None:
            return None

        start_index, end_index = best_window
        return FuzzyMatchResult(
            intent=intent_name,
            matched_value=normalized_phrase,
            score=best_score,
            start_index=start_index,
            end_index=end_index,
            token_count=len(phrase_tokens),
        )


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    without_punctuation = re.sub(r"[^a-z0-9\s]", " ", ascii_only)
    return re.sub(r"\s+", " ", without_punctuation).strip()


def tokenize_text(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    if not normalized:
        return ()
    return tuple(normalized.split())
