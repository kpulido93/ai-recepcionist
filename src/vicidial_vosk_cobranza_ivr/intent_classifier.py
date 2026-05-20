from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml


class Intent(str, Enum):
    SI = "SI"
    NO = "NO"
    INFO_COBRO = "INFO_COBRO"
    NUMERO_EQUIVOCADO = "NUMERO_EQUIVOCADO"
    NO_ES_PERSONA = "NO_ES_PERSONA"
    PROMESA_PAGO = "PROMESA_PAGO"
    CALLBACK = "CALLBACK"
    DUDA = "DUDA"
    SILENCIO = "SILENCIO"


IntentName = Intent | str
PRIORITIZED_INTENTS: tuple[Intent, ...] = (
    Intent.NO_ES_PERSONA,
    Intent.NUMERO_EQUIVOCADO,
    Intent.NO,
    Intent.CALLBACK,
    Intent.PROMESA_PAGO,
    Intent.INFO_COBRO,
    Intent.SI,
    Intent.DUDA,
)
SKIPPED_PRIORITY_INTENTS = {Intent.SILENCIO}
EARLY_DETECTION_ALLOWED_INTENTS: tuple[Intent, ...] = (
    Intent.SI,
    Intent.NO,
    Intent.INFO_COBRO,
    Intent.PROMESA_PAGO,
    Intent.NUMERO_EQUIVOCADO,
    Intent.NO_ES_PERSONA,
    Intent.CALLBACK,
)
DEFAULT_EARLY_INTENTS_CONFIG: dict[str, tuple[str, ...]] = {
    "SI": (
        "si",
        "transfierame",
        "quiero hablar",
        "comuniqueme",
    ),
    "NO": (
        "no",
        "no quiero",
        "no me transfiera",
    ),
    "INFO_COBRO": (
        "quiero saber que me estan cobrando",
        "que me estan cobrando",
        "cuanto debo",
    ),
    "PROMESA_PAGO": (
        "quiero pagar",
        "quiero resolver",
    ),
    "NUMERO_EQUIVOCADO": (
        "numero equivocado",
        "aqui no vive",
    ),
    "NO_ES_PERSONA": (
        "no soy esa persona",
        "no conozco esa deuda",
    ),
    "CALLBACK": (
        "llameme despues",
        "estoy trabajando",
    ),
    "DUDA": (
        "quien habla",
        "no entiendo",
        "no se",
    ),
    "SILENCIO": (),
}


@dataclass(frozen=True)
class IntentClassification:
    intent: IntentName
    transcript: str
    matched_value: str | None
    source: str
    confidence: float


@dataclass(frozen=True)
class PhraseMatch:
    intent: IntentName
    phrase: str
    score: float
    start_index: int
    end_index: int
    token_count: int


@dataclass(frozen=True)
class EarlyIntentMatch:
    intent: IntentName
    transcript: str
    matched_value: str
    confidence: float


@dataclass(frozen=True)
class ClassifiedIntent:
    intent: IntentName
    confidence: float
    matched_phrase: str | None
    normalized_text: str


class IntentClassifier:
    def __init__(
        self,
        phrases: Mapping[str, Sequence[str]],
        default_intent: str,
        dtmf_map: Mapping[str, str],
    ) -> None:
        self.default_intent = resolve_intent_name(default_intent)
        self.dtmf_map = {
            digit: resolve_intent_name(intent_name) for digit, intent_name in dtmf_map.items()
        }
        self.phrases: dict[IntentName, list[str]] = {}

        for intent_name, phrase_list in phrases.items():
            resolved_intent = resolve_intent_name(intent_name)
            self.phrases[resolved_intent] = [
                normalized_phrase
                for phrase in phrase_list
                if (normalized_phrase := normalize_text(phrase))
            ]

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

        original_transcript = transcript or ""
        result = classify_intent(
            original_transcript,
            intents_config={
                intent_value(intent): phrase_list for intent, phrase_list in self.phrases.items()
            },
            default_intent=self.default_intent,
        )
        source = _resolve_classification_source(result)
        return IntentClassification(
            intent=result.intent,
            transcript="" if intent_equals(result.intent, Intent.SILENCIO) else original_transcript,
            matched_value=result.matched_phrase,
            source=source,
            confidence=result.confidence,
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


def load_intents(path: Path) -> dict[str, list[str]]:
    with path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"El archivo de intents debe tener un objeto en la raiz: {path}")

    normalized_phrases: dict[str, list[str]] = {}
    for raw_intent_name, raw_phrases in loaded.items():
        if not isinstance(raw_phrases, list):
            raise ValueError(f"El intent {raw_intent_name} debe contener una lista.")

        normalized_intent_name = str(raw_intent_name).strip().upper()
        normalized_phrases[normalized_intent_name] = [
            normalized_phrase
            for phrase in raw_phrases
            if (normalized_phrase := normalize_text(str(phrase)))
        ]

    return normalized_phrases


def resolve_intent_name(value: IntentName) -> IntentName:
    if isinstance(value, Intent):
        return value

    normalized_value = str(value).strip().upper()
    return Intent.__members__.get(normalized_value, normalized_value)


def intent_value(value: IntentName) -> str:
    return value.value if isinstance(value, Intent) else value


def intent_equals(left: IntentName, right: IntentName) -> bool:
    return intent_value(resolve_intent_name(left)) == intent_value(resolve_intent_name(right))


def classify_intent(
    text: str,
    intents_config: Mapping[str, Sequence[str]],
    default_intent: IntentName = Intent.DUDA,
) -> ClassifiedIntent:
    normalized_text = normalize_text(text)
    if not normalized_text:
        return ClassifiedIntent(
            intent=Intent.SILENCIO,
            confidence=0.0,
            matched_phrase=None,
            normalized_text="",
        )

    normalized_intents = _normalize_intents_config(intents_config)
    priority_order = _build_priority_order(normalized_intents)
    matches = {
        intent: _find_best_match_for_intent(
            normalized_text=normalized_text,
            phrases=phrase_list,
            intent=intent,
        )
        for intent, phrase_list in normalized_intents.items()
    }
    no_match = matches.get(Intent.NO)
    doubt_match = matches.get(Intent.DUDA)

    for intent in (Intent.NO_ES_PERSONA, Intent.NUMERO_EQUIVOCADO):
        match = matches.get(intent)
        if match is not None:
            return _build_result_from_match(match, normalized_text)

    if _is_decisive_negative_match(no_match):
        assert no_match is not None
        return _build_result_from_match(no_match, normalized_text)

    for candidate_intent in priority_order:
        candidate = _discard_if_blocked_by_negative_context(
            matches.get(candidate_intent),
            no_match,
            doubt_match,
        )
        if candidate is not None:
            return _build_result_from_match(candidate, normalized_text)

    if doubt_match is not None:
        return _build_result_from_match(doubt_match, normalized_text)

    if no_match is not None:
        return _build_result_from_match(no_match, normalized_text)

    return ClassifiedIntent(
        intent=resolve_intent_name(default_intent),
        confidence=0.35,
        matched_phrase=None,
        normalized_text=normalized_text,
    )


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    without_punctuation = re.sub(r"[^a-z0-9\s]", " ", ascii_only)
    collapsed = re.sub(r"\s+", " ", without_punctuation).strip()
    return collapsed


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    return normalized.split()


def tokenize_text(value: str) -> tuple[str, ...]:
    return tuple(tokenize(value))


def contains_phrase_by_tokens(text: str, phrase: str) -> bool:
    text_tokens = tokenize(value=text)
    phrase_tokens = tokenize(value=phrase)
    return _contains_token_sequence(text_tokens, phrase_tokens)


def _resolve_classification_source(result: ClassifiedIntent) -> str:
    if intent_equals(result.intent, Intent.SILENCIO):
        return "silence"
    if result.matched_phrase is None:
        return "default"
    return "transcript"


def _normalize_intents_config(
    intents_config: Mapping[str, Sequence[str]],
) -> dict[IntentName, list[str]]:
    normalized_intents: dict[IntentName, list[str]] = {}
    for intent_name, phrase_list in intents_config.items():
        resolved_intent = resolve_intent_name(intent_name)
        normalized_intents[resolved_intent] = [
            normalized_phrase
            for phrase in phrase_list
            if (normalized_phrase := normalize_text(str(phrase)))
        ]
    return normalized_intents


def _build_priority_order(
    normalized_intents: Mapping[IntentName, Sequence[str]],
) -> tuple[IntentName, ...]:
    known_priority = tuple(
        intent
        for intent in PRIORITIZED_INTENTS
        if intent in normalized_intents and intent not in {Intent.NO, Intent.DUDA, Intent.SILENCIO}
    )
    custom_priority = tuple(
        intent
        for intent in normalized_intents
        if intent not in PRIORITIZED_INTENTS and not intent_equals(intent, Intent.SILENCIO)
    )
    return known_priority + custom_priority


def _find_best_match_for_intent(
    *,
    normalized_text: str,
    phrases: Sequence[str],
    intent: IntentName,
) -> PhraseMatch | None:
    tokens = tokenize_text(normalized_text)
    if not tokens:
        return None

    best_match: PhraseMatch | None = None
    for phrase in phrases:
        phrase_tokens = tokenize_text(phrase)
        match = _build_phrase_match(
            normalized_text,
            tokens,
            intent,
            phrase,
            phrase_tokens,
        )
        if match is None:
            continue

        if best_match is None:
            best_match = match
            continue

        if match.score > best_match.score:
            best_match = match
            continue

        if match.score == best_match.score and match.token_count > best_match.token_count:
            best_match = match
            continue

        if (
            match.score == best_match.score
            and match.token_count == best_match.token_count
            and len(match.phrase) > len(best_match.phrase)
        ):
            best_match = match

    return best_match


def detect_early_intent(
    partial: str,
    *,
    intents_config: Mapping[str, Sequence[str]] | None = None,
    supported_intents: Collection[str] | None = None,
) -> EarlyIntentMatch | None:
    supported_intent_names = {
        intent_value(resolve_intent_name(intent_name))
        for intent_name in (
            supported_intents
            or (intents_config.keys() if intents_config is not None else Intent.__members__.keys())
        )
    }
    effective_intents_config = _resolve_early_intents_config(
        intents_config=intents_config,
        supported_intent_names=supported_intent_names,
    )
    result = classify_intent(
        partial,
        intents_config=effective_intents_config,
        default_intent=Intent.DUDA,
    )
    if result.matched_phrase is None:
        return None
    if intent_value(result.intent) not in supported_intent_names:
        return None
    if result.intent not in EARLY_DETECTION_ALLOWED_INTENTS:
        return None
    if intent_equals(result.intent, Intent.DUDA) or intent_equals(result.intent, Intent.SILENCIO):
        return None

    return EarlyIntentMatch(
        intent=result.intent,
        transcript=result.normalized_text,
        matched_value=result.matched_phrase,
        confidence=result.confidence,
    )


def _build_classification(match: PhraseMatch, transcript: str) -> IntentClassification:
    return IntentClassification(
        intent=match.intent,
        transcript=transcript,
        matched_value=match.phrase,
        source="transcript",
        confidence=match.score,
    )


def _build_result_from_match(match: PhraseMatch, normalized_text: str) -> ClassifiedIntent:
    return ClassifiedIntent(
        intent=match.intent,
        confidence=match.score,
        matched_phrase=match.phrase,
        normalized_text=normalized_text,
    )


def _match_score(normalized_text: str, phrase: str) -> float:
    if not phrase:
        return 0.0

    if normalized_text == phrase:
        return 1.0

    if contains_phrase_by_tokens(normalized_text, phrase):
        token_bonus = min(0.1, len(phrase.split()) * 0.03)
        return round(0.8 + token_bonus, 2)

    return 0.0


def _build_phrase_match(
    normalized_text: str,
    tokens: tuple[str, ...],
    intent: IntentName,
    phrase: str,
    phrase_tokens: tuple[str, ...],
) -> PhraseMatch | None:
    positions = _find_token_sequence_positions(tokens, phrase_tokens)
    if not positions:
        return None

    score = _match_score(normalized_text, phrase)
    if score <= 0.0:
        return None

    start_index, end_index = positions[0]
    return PhraseMatch(
        intent=intent,
        phrase=phrase,
        score=score,
        start_index=start_index,
        end_index=end_index,
        token_count=len(phrase_tokens),
    )


def _resolve_early_intents_config(
    *,
    intents_config: Mapping[str, Sequence[str]] | None,
    supported_intent_names: set[str],
) -> dict[str, Sequence[str]]:
    if intents_config is None:
        return {
            intent_name: phrase_list
            for intent_name, phrase_list in DEFAULT_EARLY_INTENTS_CONFIG.items()
            if intent_name in supported_intent_names
        }

    return {
        intent_value(resolve_intent_name(intent_name)): phrase_list
        for intent_name, phrase_list in intents_config.items()
        if intent_value(resolve_intent_name(intent_name)) in supported_intent_names
    }


def _contains_token_sequence(tokens: Sequence[str], phrase_tokens: Sequence[str]) -> bool:
    return bool(_find_token_sequence_positions(tokens, phrase_tokens))


def _find_token_sequence_positions(
    tokens: Sequence[str],
    phrase_tokens: Sequence[str],
) -> list[tuple[int, int]]:
    phrase_length = len(phrase_tokens)
    if phrase_length == 0 or len(tokens) < phrase_length:
        return []

    positions: list[tuple[int, int]] = []
    for index in range(len(tokens) - phrase_length + 1):
        if tokens[index : index + phrase_length] == phrase_tokens:
            positions.append((index, index + phrase_length))
    return positions


def _discard_if_blocked_by_negative_context(
    candidate: PhraseMatch | None,
    no_match: PhraseMatch | None,
    doubt_match: PhraseMatch | None,
) -> PhraseMatch | None:
    if candidate is None:
        return None

    if _is_decisive_negative_match(no_match) and _matches_touch_or_overlap(candidate, no_match):
        return None

    if _is_uncertainty_blocker(doubt_match) and _matches_touch_or_overlap(candidate, doubt_match):
        return None

    return candidate


def _is_decisive_negative_match(match: PhraseMatch | None) -> bool:
    if match is None:
        return False
    if match.score == 1.0:
        return True
    return match.token_count > 1


def _is_uncertainty_blocker(match: PhraseMatch | None) -> bool:
    if match is None:
        return False
    return match.phrase.startswith("no ")


def _matches_touch_or_overlap(left: PhraseMatch, right: PhraseMatch | None) -> bool:
    if right is None:
        return False
    return left.end_index >= right.start_index and right.end_index >= left.start_index
