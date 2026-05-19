from __future__ import annotations

from pathlib import Path

import pytest

from vicidial_vosk_cobranza_ivr.intent_classifier import Intent, IntentClassifier, load_intents


def build_classifier() -> IntentClassifier:
    return IntentClassifier(
        phrases={
            "SI": [
                "si",
                "quiero hablar",
                "paseme con un abogado",
                "comuniqueme",
                "abogado",
            ],
            "NO": [
                "no",
                "ahora no",
                "no quiero",
                "no puedo",
            ],
            "DUDA": [
                "quien habla",
                "no entiendo",
                "no se",
            ],
            "SILENCIO": [],
        },
        default_intent="DUDA",
        dtmf_map={"1": "SI", "2": "NO"},
    )


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
        "páseme con un abogado",
        "por favor comuniqueme con el abogado",
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
        "disculpe, no puedo atender",
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
        "tal vez despues",
    ],
)
def test_classifies_ambiguous_text(transcript: str) -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript=transcript)

    assert result.intent is Intent.DUDA


def test_classifies_text_with_accents() -> None:
    classifier = build_classifier()

    result = classifier.classify(transcript="páseme con un abogado")

    assert result.intent is Intent.SI
    assert result.matched_value == "paseme con un abogado"


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


def test_returns_duda_when_yes_and_no_appear_together() -> None:
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


def test_loads_intents_from_yaml_file() -> None:
    intents = load_intents(Path("config/intents.yml"))
    classifier = IntentClassifier(
        phrases=intents,
        default_intent="DUDA",
        dtmf_map={},
    )

    result = classifier.classify(transcript="páseme con un abogado")

    assert result.intent is Intent.SI
