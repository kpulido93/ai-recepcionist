from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from vicidial_vosk_cobranza_ivr.blocklist import BlocklistMatcher
from vicidial_vosk_cobranza_ivr.fuzzy_matcher import (
    DEFAULT_FUZZY_THRESHOLD,
    FuzzyMatcher,
    FuzzyMatchResult,
)
from vicidial_vosk_cobranza_ivr.fuzzy_matcher import (
    normalize_text as _normalize_text,
)
from vicidial_vosk_cobranza_ivr.fuzzy_matcher import (
    tokenize_text as _tokenize_text,
)

LOGGER = logging.getLogger(__name__)


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
    TRANSFER_REQUEST = "TRANSFER_REQUEST"
    YA_PAGO = "YA_PAGO"
    QUIERE_ACUERDO = "QUIERE_ACUERDO"
    INFO_DEUDA = "INFO_DEUDA"
    DISPUTA_DEUDA = "DISPUTA_DEUDA"
    NO_PUEDE_PAGAR = "NO_PUEDE_PAGAR"
    TERCERO = "TERCERO"
    FRAUDE_O_DESCONFIANZA = "FRAUDE_O_DESCONFIANZA"
    VULGARIDAD = "VULGARIDAD"
    AMENAZA_VERBAL = "AMENAZA_VERBAL"


IntentName = Intent | str
PRIORITIZED_INTENTS: tuple[Intent, ...] = (
    Intent.AMENAZA_VERBAL,
    Intent.VULGARIDAD,
    Intent.NUMERO_EQUIVOCADO,
    Intent.NO_ES_PERSONA,
    Intent.TERCERO,
    Intent.NO,
    Intent.CALLBACK,
    Intent.FRAUDE_O_DESCONFIANZA,
    Intent.DISPUTA_DEUDA,
    Intent.NO_PUEDE_PAGAR,
    Intent.YA_PAGO,
    Intent.QUIERE_ACUERDO,
    Intent.PROMESA_PAGO,
    Intent.INFO_DEUDA,
    Intent.INFO_COBRO,
    Intent.TRANSFER_REQUEST,
    Intent.SI,
    Intent.DUDA,
)
SKIPPED_PRIORITY_INTENTS = {Intent.SILENCIO}
EARLY_DETECTION_ALLOWED_INTENTS: tuple[Intent, ...] = (
    Intent.AMENAZA_VERBAL,
    Intent.VULGARIDAD,
    Intent.NUMERO_EQUIVOCADO,
    Intent.NO_ES_PERSONA,
    Intent.TERCERO,
    Intent.NO,
    Intent.CALLBACK,
    Intent.FRAUDE_O_DESCONFIANZA,
    Intent.YA_PAGO,
    Intent.QUIERE_ACUERDO,
    Intent.PROMESA_PAGO,
    Intent.INFO_DEUDA,
    Intent.INFO_COBRO,
    Intent.TRANSFER_REQUEST,
    Intent.SI,
)
DEFAULT_EARLY_INTENTS_CONFIG: dict[str, tuple[str, ...]] = {
    "SI": (
        "si",
        "claro",
        "de acuerdo",
        "correcto",
    ),
    "TRANSFER_REQUEST": (
        "comuniqueme",
        "transfierame",
        "quiero hablar con un asesor",
        "quiero hablar con una persona",
        "me puede comunicar",
    ),
    "INFO_COBRO": (
        "quiero informacion",
        "expliqueme el cobro",
    ),
    "INFO_DEUDA": (
        "cuanto debo",
        "de que es la deuda",
        "quiero informacion de la deuda",
    ),
    "PROMESA_PAGO": (
        "quiero pagar",
        "voy a pagar",
        "puedo pagar hoy",
    ),
    "QUIERE_ACUERDO": (
        "quiero hacer un acuerdo",
        "quiero llegar a un acuerdo",
    ),
    "YA_PAGO": (
        "ya pague",
        "ya realice el pago",
    ),
    "NO": (
        "no",
        "no quiero",
        "no me transfiera",
        "no me comuniquen",
        "no llamen mas",
    ),
    "NUMERO_EQUIVOCADO": (
        "numero equivocado",
        "este no es su numero",
    ),
    "NO_ES_PERSONA": (
        "no soy esa persona",
        "no esta esa persona",
    ),
    "TERCERO": (
        "soy familiar",
        "soy tercero",
    ),
    "CALLBACK": (
        "llameme despues",
        "estoy ocupado",
    ),
    "FRAUDE_O_DESCONFIANZA": (
        "esto es fraude",
        "no confio",
    ),
    "DUDA": (
        "quien habla",
        "no entiendo",
        "repita",
    ),
    "SILENCIO": (),
}
DEFAULT_SEMANTIC_THRESHOLD = 0.72
DEFAULT_SEMANTIC_MIN_CONFIDENCE = 0.70
CRITICAL_BLOCKING_INTENTS: tuple[Intent, ...] = (
    Intent.AMENAZA_VERBAL,
    Intent.VULGARIDAD,
    Intent.NUMERO_EQUIVOCADO,
    Intent.NO_ES_PERSONA,
    Intent.TERCERO,
)


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


@dataclass(frozen=True)
class SemanticClassifierConfig:
    enabled: bool = True
    fuzzy_enabled: bool = True
    semantic_enabled: bool = False
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    min_confidence: float = DEFAULT_SEMANTIC_MIN_CONFIDENCE


class IntentClassifier:
    def __init__(
        self,
        phrases: Mapping[str, Sequence[str]],
        default_intent: str,
        dtmf_map: Mapping[str, str],
        semantic_config: Mapping[str, object] | None = None,
        semantic_intents: Mapping[str, Mapping[str, Sequence[str]] | Sequence[str]] | None = None,
        blocklist_matcher: BlocklistMatcher | None = None,
    ) -> None:
        self.default_intent = resolve_intent_name(default_intent)
        self.dtmf_map = {
            digit: resolve_intent_name(intent_name) for digit, intent_name in dtmf_map.items()
        }
        self.semantic_config = _resolve_semantic_classifier_config(semantic_config)
        self.blocklist_matcher = blocklist_matcher
        self.phrases: dict[IntentName, list[str]] = _normalize_intents_config(phrases)
        self.semantic_phrases = _normalize_semantic_intents_config(semantic_intents or {})
        self.fuzzy_matcher = FuzzyMatcher(
            threshold=max(
                self.semantic_config.fuzzy_threshold,
                self.semantic_config.min_confidence,
            )
        )

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
        blocklist_classification = self._classify_blocklist(original_transcript)
        if blocklist_classification is not None:
            return blocklist_classification

        result = classify_intent(
            original_transcript,
            intents_config={
                intent_value(intent): phrase_list for intent, phrase_list in self.phrases.items()
            },
            default_intent=self.default_intent,
        )
        fuzzy_classification = self._classify_fuzzy(
            transcript=original_transcript,
            exact_result=result,
        )
        if fuzzy_classification is not None:
            return fuzzy_classification

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

    def detect_early_intent(self, partial: str) -> EarlyIntentMatch | None:
        return detect_early_intent(
            partial,
            intents_config={
                intent_value(intent): phrases for intent, phrases in self.phrases.items()
            },
            supported_intents={
                intent_value(intent)
                for intent in self.phrases
                if intent not in SKIPPED_PRIORITY_INTENTS
            },
            blocklist_matcher=self.blocklist_matcher,
        )

    def _classify_blocklist(self, transcript: str) -> IntentClassification | None:
        if self.blocklist_matcher is None:
            return None

        match = self.blocklist_matcher.match(transcript)
        if match is None:
            return None

        normalized_text = normalize_text(transcript)
        LOGGER.info(
            (
                "Intent blocklist match normalized=%s intent=%s "
                "category=%s matched=%s source=transcript"
            ),
            normalized_text,
            match.intent,
            match.category,
            match.matched_value,
        )
        return IntentClassification(
            intent=resolve_intent_name(match.intent),
            transcript=transcript,
            matched_value=match.matched_value,
            source="transcript",
            confidence=1.0,
        )

    def _classify_fuzzy(
        self,
        *,
        transcript: str,
        exact_result: ClassifiedIntent,
    ) -> IntentClassification | None:
        if not self.semantic_config.enabled or not self.semantic_config.fuzzy_enabled:
            return None
        if (
            intent_equals(exact_result.intent, Intent.SILENCIO)
            or exact_result.matched_phrase is not None
        ):
            return None

        normalized_text = exact_result.normalized_text
        if not normalized_text:
            return None

        normalized_intents = self._build_fuzzy_intents_config()
        if not normalized_intents:
            return None

        priority_order = _build_priority_order(normalized_intents)
        matches = {
            intent: _find_best_fuzzy_match_for_intent(
                normalized_text=normalized_text,
                phrases=phrase_list,
                intent=intent,
                fuzzy_matcher=self.fuzzy_matcher,
            )
            for intent, phrase_list in normalized_intents.items()
        }
        selected_match = _select_best_intent_match(matches, priority_order)
        if selected_match is None:
            return None

        LOGGER.info(
            "Intent fuzzy match normalized=%s intent=%s candidate=%s score=%.2f source=fuzzy",
            normalized_text,
            intent_value(selected_match.intent),
            selected_match.phrase,
            selected_match.score,
        )
        return IntentClassification(
            intent=selected_match.intent,
            transcript=transcript,
            matched_value=selected_match.phrase,
            source="fuzzy",
            confidence=selected_match.score,
        )

    def _build_fuzzy_intents_config(self) -> dict[IntentName, list[str]]:
        intents: dict[IntentName, list[str]] = {
            intent: list(phrases) for intent, phrases in self.phrases.items()
        }

        for intent, phrase_groups in self.semantic_phrases.items():
            intent_phrases = intents.setdefault(intent, [])
            intent_phrases.extend(phrase_groups)
            intents[intent] = list(dict.fromkeys(intent_phrases))

        return intents


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
    selected_match = _select_best_intent_match(matches, priority_order)
    if selected_match is not None:
        return _build_result_from_match(selected_match, normalized_text)

    return ClassifiedIntent(
        intent=resolve_intent_name(default_intent),
        confidence=0.35,
        matched_phrase=None,
        normalized_text=normalized_text,
    )


def normalize_text(value: str) -> str:
    return _normalize_text(value)


def tokenize(value: str) -> list[str]:
    normalized = normalize_text(value)
    if not normalized:
        return []
    return normalized.split()


def tokenize_text(value: str) -> tuple[str, ...]:
    return _tokenize_text(value)


def contains_phrase_by_tokens(text: str, phrase: str) -> bool:
    text_tokens = tokenize(value=text)
    phrase_tokens = tokenize(value=phrase)
    return _contains_token_sequence(text_tokens, phrase_tokens)


def detect_early_intent(
    partial: str,
    *,
    intents_config: Mapping[str, Sequence[str]] | None = None,
    supported_intents: Collection[str] | None = None,
    blocklist_matcher: BlocklistMatcher | None = None,
) -> EarlyIntentMatch | None:
    normalized_partial = normalize_text(partial)
    if not normalized_partial:
        return None

    if blocklist_matcher is not None:
        blocklist_match = blocklist_matcher.match(normalized_partial)
        if blocklist_match is not None:
            return EarlyIntentMatch(
                intent=resolve_intent_name(blocklist_match.intent),
                transcript=normalized_partial,
                matched_value=blocklist_match.matched_value,
                confidence=1.0,
            )

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


def _normalize_semantic_intents_config(
    semantic_intents: Mapping[str, Mapping[str, Sequence[str]] | Sequence[str]],
) -> dict[IntentName, list[str]]:
    normalized_intents: dict[IntentName, list[str]] = {}
    for intent_name, raw_phrase_groups in semantic_intents.items():
        resolved_intent = resolve_intent_name(intent_name)
        collected_phrases: list[str] = []

        if isinstance(raw_phrase_groups, Mapping):
            for group_name in ("canonical", "aliases"):
                raw_phrases = raw_phrase_groups.get(group_name, ())
                if isinstance(raw_phrases, str):
                    raw_values: Sequence[str] = (raw_phrases,)
                else:
                    raw_values = raw_phrases
                collected_phrases.extend(
                    normalized_phrase
                    for phrase in raw_values
                    if (normalized_phrase := normalize_text(str(phrase)))
                )
        elif isinstance(raw_phrase_groups, str):
            normalized_phrase = normalize_text(raw_phrase_groups)
            if normalized_phrase:
                collected_phrases.append(normalized_phrase)
        else:
            collected_phrases.extend(
                normalized_phrase
                for phrase in raw_phrase_groups
                if (normalized_phrase := normalize_text(str(phrase)))
            )

        normalized_intents[resolved_intent] = list(dict.fromkeys(collected_phrases))

    return normalized_intents


def _resolve_semantic_classifier_config(
    semantic_config: Mapping[str, object] | None,
) -> SemanticClassifierConfig:
    if semantic_config is None:
        return SemanticClassifierConfig()

    return SemanticClassifierConfig(
        enabled=bool(semantic_config.get("enabled", True)),
        fuzzy_enabled=bool(semantic_config.get("fuzzy_enabled", True)),
        semantic_enabled=bool(semantic_config.get("semantic_enabled", False)),
        fuzzy_threshold=_coerce_float(
            semantic_config.get("fuzzy_threshold", DEFAULT_FUZZY_THRESHOLD)
        ),
        semantic_threshold=_coerce_float(
            semantic_config.get("semantic_threshold", DEFAULT_SEMANTIC_THRESHOLD)
        ),
        min_confidence=_coerce_float(
            semantic_config.get("min_confidence", DEFAULT_SEMANTIC_MIN_CONFIDENCE)
        ),
    )


def _coerce_float(value: object) -> float:
    if isinstance(value, (float, int)):
        return float(value)
    return float(str(value))


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


def _select_best_intent_match(
    matches: Mapping[IntentName, PhraseMatch | None],
    priority_order: Sequence[IntentName],
) -> PhraseMatch | None:
    for intent in CRITICAL_BLOCKING_INTENTS:
        match = matches.get(intent)
        if match is not None:
            return match

    no_match = matches.get(Intent.NO)
    doubt_match = matches.get(Intent.DUDA)

    if _is_decisive_negative_match(no_match):
        assert no_match is not None
        return no_match

    candidates = [
        candidate
        for candidate_intent in priority_order
        if (
            candidate := _discard_if_blocked_by_negative_context(
                matches.get(candidate_intent),
                no_match,
                doubt_match,
            )
        )
        is not None
    ]
    if candidates:
        return _select_highest_scoring_match(candidates, priority_order)

    if doubt_match is not None:
        return doubt_match

    if no_match is not None:
        return no_match

    return None


def _select_highest_scoring_match(
    candidates: Sequence[PhraseMatch],
    priority_order: Sequence[IntentName],
) -> PhraseMatch:
    priority_rank = {intent_value(intent): index for index, intent in enumerate(priority_order)}
    return max(
        candidates,
        key=lambda candidate: (
            candidate.score,
            candidate.token_count,
            len(candidate.phrase),
            -priority_rank.get(intent_value(candidate.intent), len(priority_rank)),
        ),
    )


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


def _find_best_fuzzy_match_for_intent(
    *,
    normalized_text: str,
    phrases: Sequence[str],
    intent: IntentName,
    fuzzy_matcher: FuzzyMatcher,
) -> PhraseMatch | None:
    result = fuzzy_matcher.match(
        normalized_text,
        {intent_value(intent): phrases},
    )
    if result is None:
        return None
    return _build_phrase_match_from_fuzzy_result(intent, result)


def _build_phrase_match_from_fuzzy_result(
    intent: IntentName,
    result: FuzzyMatchResult,
) -> PhraseMatch:
    return PhraseMatch(
        intent=intent,
        phrase=result.matched_value,
        score=result.score,
        start_index=result.start_index,
        end_index=result.end_index,
        token_count=result.token_count,
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
    return match is not None


def _matches_touch_or_overlap(left: PhraseMatch, right: PhraseMatch | None) -> bool:
    if right is None:
        return False
    return left.end_index >= right.start_index and right.end_index >= left.start_index
