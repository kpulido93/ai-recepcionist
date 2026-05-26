from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT
from vicidial_vosk_cobranza_ivr.fuzzy_matcher import normalize_text, tokenize_text

DEFAULT_BLOCKLIST_SAMPLE_PATH = PROJECT_ROOT / "config" / "blocklist.sample.yml"
DEFAULT_BLOCKLIST_LOCAL_PATH = PROJECT_ROOT / "config" / "local" / "blocklist.yml"

CATEGORY_INTENT_MAP = {
    "abusive_language": "VULGARIDAD",
    "verbal_threats": "AMENAZA_VERBAL",
}


@dataclass(frozen=True)
class BlocklistCategory:
    enabled: bool = True
    terms: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class BlocklistConfig:
    abusive_language: BlocklistCategory = BlocklistCategory()
    verbal_threats: BlocklistCategory = BlocklistCategory()


@dataclass(frozen=True)
class BlocklistMatch:
    intent: str
    category: str
    matched_value: str


class BlocklistMatcher:
    def __init__(self, config: BlocklistConfig) -> None:
        self.config = config

    @classmethod
    def from_paths(
        cls,
        sample_path: Path = DEFAULT_BLOCKLIST_SAMPLE_PATH,
        local_path: Path = DEFAULT_BLOCKLIST_LOCAL_PATH,
    ) -> BlocklistMatcher:
        return cls(load_blocklist_config(sample_path=sample_path, local_path=local_path))

    @classmethod
    def from_mapping(cls, raw_config: Mapping[str, Any]) -> BlocklistMatcher:
        return cls(build_blocklist_config(raw_config))

    def match(self, transcript: str) -> BlocklistMatch | None:
        normalized_text = normalize_text(transcript)
        if not normalized_text:
            return None

        tokens = tokenize_text(normalized_text)
        if not tokens:
            return None

        for category_name, intent_name in CATEGORY_INTENT_MAP.items():
            category = getattr(self.config, category_name)
            if not category.enabled:
                continue

            matched_phrase = _find_phrase_match(tokens, category.phrases)
            if matched_phrase is not None:
                return BlocklistMatch(
                    intent=intent_name,
                    category=category_name,
                    matched_value=sanitize_blocklist_match(matched_phrase),
                )

            matched_term = _find_term_match(tokens, category.terms)
            if matched_term is not None:
                return BlocklistMatch(
                    intent=intent_name,
                    category=category_name,
                    matched_value=sanitize_blocklist_match(matched_term),
                )

        return None


def load_blocklist_config(
    sample_path: Path = DEFAULT_BLOCKLIST_SAMPLE_PATH,
    local_path: Path = DEFAULT_BLOCKLIST_LOCAL_PATH,
) -> BlocklistConfig:
    merged = _load_yaml_dict(sample_path)
    local_values = _load_yaml_dict(local_path, required=False)
    for category_name, category_config in local_values.items():
        merged.setdefault(category_name, {})
        merged[category_name].update(category_config)
    return build_blocklist_config(merged)


def build_blocklist_config(raw_config: Mapping[str, Any]) -> BlocklistConfig:
    return BlocklistConfig(
        abusive_language=_build_category(raw_config.get("abusive_language", {})),
        verbal_threats=_build_category(raw_config.get("verbal_threats", {})),
    )


def sanitize_blocklist_match(value: str) -> str:
    normalized_value = normalize_text(value)
    if not normalized_value:
        return "redacted[0]"
    return f"redacted[{len(normalized_value)}]"


def _build_category(raw_value: object) -> BlocklistCategory:
    if not isinstance(raw_value, Mapping):
        return BlocklistCategory()
    return BlocklistCategory(
        enabled=bool(raw_value.get("enabled", True)),
        terms=_normalize_values(raw_value.get("terms", ())),
        phrases=_normalize_values(raw_value.get("phrases", ())),
    )


def _normalize_values(raw_values: object) -> tuple[str, ...]:
    if isinstance(raw_values, str):
        values: Sequence[object] = (raw_values,)
    elif isinstance(raw_values, Sequence):
        values = raw_values
    else:
        values = ()
    normalized = [
        normalized_value for value in values if (normalized_value := normalize_text(str(value)))
    ]
    return tuple(dict.fromkeys(normalized))


def _find_phrase_match(tokens: Sequence[str], phrases: Sequence[str]) -> str | None:
    best_match: str | None = None
    for phrase in phrases:
        phrase_tokens = tokenize_text(phrase)
        if not phrase_tokens or len(tokens) < len(phrase_tokens):
            continue
        for index in range(len(tokens) - len(phrase_tokens) + 1):
            if tokens[index : index + len(phrase_tokens)] == phrase_tokens:
                if best_match is None or len(phrase_tokens) > len(tokenize_text(best_match)):
                    best_match = phrase
                break
    return best_match


def _find_term_match(tokens: Sequence[str], terms: Sequence[str]) -> str | None:
    token_set = set(tokens)
    for term in terms:
        term_tokens = tokenize_text(term)
        if not term_tokens:
            continue
        if len(term_tokens) == 1:
            if term_tokens[0] in token_set:
                return term
            continue
        for index in range(len(tokens) - len(term_tokens) + 1):
            if tuple(tokens[index : index + len(term_tokens)]) == term_tokens:
                return term
    return None


def _load_yaml_dict(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}

    with path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or {}

    if not isinstance(loaded, dict):
        raise ValueError(f"El blocklist debe ser un objeto YAML: {path}")
    return {str(key): value for key, value in loaded.items() if isinstance(value, Mapping)}
