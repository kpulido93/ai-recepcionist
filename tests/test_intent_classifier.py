from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vicidial_vosk_cobranza_ivr.intent_classifier import (
    ClassifiedIntent,
    Intent,
    IntentClassifier,
    classify_intent,
    contains_phrase_by_tokens,
    detect_early_intent,
    load_intents,
    normalize_text,
    tokenize,
)


def build_classifier() -> IntentClassifier:
    return IntentClassifier(
        phrases=build_intents_config(),
        default_intent="DUDA",
        dtmf_map={"1": "SI", "2": "NO"},
    )


def build_intents_config() -> dict[str, list[str]]:
    return {
        "SI": [
            "si",
            "transfierame",
            "quiero hablar",
            "comuniqueme",
            "quiero hablar con un representante",
        ],
        "INFO_COBRO": [
            "quiero saber que me estan cobrando",
            "cuanto debo",
            "que es lo que me estan cobrando",
        ],
        "PROMESA_PAGO": [
            "quiero pagar",
            "quiero resolver",
            "voy a pagar",
        ],
        "CALLBACK": [
            "llameme despues",
            "ahora estoy ocupado",
        ],
        "NUMERO_EQUIVOCADO": [
            "numero equivocado",
            "aqui no vive",
        ],
        "NO_ES_PERSONA": [
            "no soy esa persona",
            "no conozco esa deuda",
        ],
        "NO": [
            "no",
            "ahora no",
            "no quiero",
            "no quiero hablar",
            "no puedo ahora",
            "no me transfiera",
            "despues",
        ],
        "DUDA": [
            "quien habla",
            "no entiendo",
            "no se",
            "que es esto",
        ],
        "SILENCIO": [],
    }


def test_normalize_text_removes_accents_and_punctuation() -> None:
    assert normalize_text("Sí, transfiérame.") == "si transfierame"


def test_normalize_text_preserves_numbers() -> None:
    assert normalize_text("¿Qué me están cobrando? 123") == "que me estan cobrando 123"


def test_tokenize_returns_token_list() -> None:
    assert tokenize("No   me transfiera 123") == ["no", "me", "transfiera", "123"]


@pytest.mark.parametrize(
    ("text", "phrase", "expected"),
    [
        ("silla rota", "si", False),
        ("noticia urgente", "no", False),
        ("sino", "si", False),
        ("sino", "no", False),
        ("pago pendiente", "pa", False),
        ("no me transfiera", "no", True),
        ("quiero saber que me estan cobrando", "que me estan cobrando", True),
        ("ta bien, comuniqueme", "ta bien", True),
    ],
)
def test_contains_phrase_by_tokens_avoids_substring_false_positives(
    text: str,
    phrase: str,
    expected: bool,
) -> None:
    assert contains_phrase_by_tokens(text, phrase) is expected


@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_phrase", "expected_normalized"),
    [
        ("no me transfiera", Intent.NO, "no me transfiera", "no me transfiera"),
        ("no quiero hablar", Intent.NO, "no quiero hablar", "no quiero hablar"),
        ("si transfierame", Intent.SI, "transfierame", "si transfierame"),
        (
            "quiero saber que me estan cobrando",
            Intent.INFO_COBRO,
            "quiero saber que me estan cobrando",
            "quiero saber que me estan cobrando",
        ),
        ("quiero pagar", Intent.PROMESA_PAGO, "quiero pagar", "quiero pagar"),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO, "numero equivocado", "numero equivocado"),
        ("no soy esa persona", Intent.NO_ES_PERSONA, "no soy esa persona", "no soy esa persona"),
        ("llameme despues", Intent.CALLBACK, "llameme despues", "llameme despues"),
        ("silla", Intent.DUDA, None, "silla"),
        ("", Intent.SILENCIO, None, ""),
    ],
)
def test_classify_intent_returns_deterministic_result(
    text: str,
    expected_intent: Intent,
    expected_phrase: str | None,
    expected_normalized: str,
) -> None:
    result = classify_intent(text, build_intents_config())

    assert isinstance(result, ClassifiedIntent)
    assert result.intent is expected_intent
    assert result.matched_phrase == expected_phrase
    assert result.normalized_text == expected_normalized
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("si", Intent.SI),
        ("sí", Intent.SI),
    ],
)
def test_classifies_simple_affirmatives(transcript: str, expected_intent: Intent) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is expected_intent
    assert result.confidence > 0.0


@pytest.mark.parametrize(
    "transcript",
    [
        "sí quiero hablar",
        "por favor comuníqueme",
        "quiero hablar con un representante",
    ],
)
def test_classifies_long_affirmative_phrases(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.SI
    assert result.confidence > 0.0


@pytest.mark.parametrize(
    "transcript",
    [
        "no",
        "NO",
    ],
)
def test_classifies_simple_negatives(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.NO
    assert result.confidence > 0.0


@pytest.mark.parametrize(
    "transcript",
    [
        "ahora no puedo",
        "disculpe, no puedo ahora",
        "por ahora no, gracias",
    ],
)
def test_classifies_long_negative_phrases(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.NO
    assert result.confidence > 0.0


@pytest.mark.parametrize(
    "transcript",
    [
        "",
        "   ",
    ],
)
def test_classifies_silence(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.SILENCIO
    assert result.confidence == 0.0


@pytest.mark.parametrize(
    "transcript",
    [
        "quién habla",
        "no entiendo",
        "repita",
    ],
)
def test_classifies_ambiguous_text(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.DUDA


def test_classifies_text_with_accents() -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript="transfiérame")

    assert result.intent is Intent.SI
    assert result.matched_value == "transfierame"


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("¡Sí, quiero hablar!", Intent.SI),
        ("¿Quién habla?", Intent.DUDA),
        ("No, gracias.", Intent.NO),
    ],
)
def test_classifies_text_with_punctuation(transcript: str, expected_intent: Intent) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is expected_intent


def test_returns_duda_when_yes_and_doubt_appear_together() -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript="si no se")

    assert result.intent is Intent.DUDA
    assert result.confidence > 0.0


def test_classifies_dtmf_before_transcript() -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript="no", dtmf="1")

    assert result.intent is Intent.SI
    assert result.source == "dtmf"
    assert result.confidence == 1.0


def test_classifies_dtmf_two_before_affirmative_transcript() -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript="sí", dtmf="2")

    assert result.intent is Intent.NO
    assert result.source == "dtmf"
    assert result.confidence == 1.0


def test_load_intents_keeps_yaml_keys_as_strings() -> None:
    raw_intents = yaml.safe_load(Path("config/intents.yml").read_text(encoding="utf-8"))
    intents = load_intents(Path("config/intents.yml"))

    assert all(isinstance(key, str) for key in raw_intents)
    assert all(isinstance(key, str) for key in intents)
    assert "NO" in raw_intents
    assert "NO" in intents
    assert not any(isinstance(key, bool) for key in raw_intents)


def test_loads_intents_from_yaml_file() -> None:
    intents = load_intents(Path("config/intents.yml"))
    classifier = IntentClassifier(
        phrases=intents,
        default_intent="DUDA",
        dtmf_map={},
    )

    result = classifier.classify(transcript="quiero hablar con un representante")

    assert result.intent is Intent.SI


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("quiero saber que me estan cobrando", Intent.INFO_COBRO),
        ("cuanto debo", Intent.INFO_COBRO),
        ("si transfierame", Intent.SI),
        ("no me transfiera", Intent.NO),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO),
        ("no soy esa persona", Intent.NO_ES_PERSONA),
        ("quiero pagar", Intent.PROMESA_PAGO),
        ("llameme despues", Intent.CALLBACK),
    ],
)
def test_classifies_rd_cobranza_phrases_from_yaml(
    transcript: str,
    expected_intent: Intent,
) -> None:
    intents = load_intents(Path("config/intents.yml"))
    classifier = IntentClassifier(
        phrases=intents,
        default_intent="DUDA",
        dtmf_map={},
    )

    result = classifier.classify(transcript=transcript)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("no me transfiera", Intent.NO),
        ("si transfierame", Intent.SI),
        ("quiero saber que me estan cobrando", Intent.INFO_COBRO),
        ("no se cuanto debo", Intent.DUDA),
        ("llameme despues", Intent.CALLBACK),
        ("quiero pagar", Intent.PROMESA_PAGO),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO),
    ],
)
def test_prioritizes_specific_cobranza_matches_over_weaker_overlaps(
    transcript: str,
    expected_intent: Intent,
) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is expected_intent


def test_classifier_accepts_custom_intents_without_breaking_known_ones() -> None:
    classifier = IntentClassifier(
        phrases={
            "RECLAMO": ["quiero poner una queja"],
            "DUDA": ["quien habla"],
            "SILENCIO": [],
        },
        default_intent="DUDA",
        dtmf_map={},
    )

    result = classifier.classify(transcript="quiero poner una queja")

    assert result.intent == "RECLAMO"


@pytest.mark.parametrize(
    ("partial", "supported_intents", "expected_intent"),
    [
        ("si", None, Intent.SI),
        ("si transfierame", None, Intent.SI),
        ("quiero saber que me estan cobrando", None, Intent.INFO_COBRO),
        ("quiero pagar", None, Intent.PROMESA_PAGO),
        ("no me transfiera", None, Intent.NO),
        ("numero equivocado", None, Intent.NUMERO_EQUIVOCADO),
        ("llameme despues", None, Intent.CALLBACK),
    ],
)
def test_detects_early_intent_from_partial(
    partial: str,
    supported_intents: set[str] | None,
    expected_intent: Intent,
) -> None:
    match = detect_early_intent(
        partial,
        intents_config=build_intents_config(),
        supported_intents=supported_intents,
    )

    assert match is not None
    assert match.intent is expected_intent


def test_does_not_detect_early_intent_when_specific_intent_is_not_supported() -> None:
    match = detect_early_intent(
        "quiero saber que me estan cobrando",
        intents_config=build_intents_config(),
        supported_intents={"SI", "NO", "DUDA", "SILENCIO"},
    )

    assert match is None


@pytest.mark.parametrize("partial", ["silla", "noticia", "sino"])
def test_does_not_detect_early_intent_on_substring_false_positive(partial: str) -> None:
    assert detect_early_intent(partial, intents_config=build_intents_config()) is None
