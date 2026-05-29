from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from vicidial_vosk_cobranza_ivr.blocklist import BlocklistMatcher
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
        semantic_config=build_semantic_classifier_config(),
        semantic_intents=build_semantic_intents_config(),
        blocklist_matcher=build_blocklist_matcher(),
    )


def build_intents_config() -> dict[str, list[str]]:
    return {
        "SI": ["si", "claro", "de acuerdo"],
        "TRANSFER_REQUEST": [
            "comuniqueme",
            "transfierame",
            "quiero hablar con un asesor",
            "me pasan con cartera",
            "paseme con cartera",
            "pasame con cartera",
            "quiero hablar con cartera",
            "me comunica con cartera",
            "comuniqueme con cartera",
        ],
        "INFO_COBRO": ["quiero informacion", "expliqueme el cobro"],
        "INFO_DEUDA": [
            "cuanto debo",
            "quiero informacion de la deuda",
            "quiero saber cuanto es la deuda",
            "quiero saber cuanto debo",
            "cuanto es la deuda",
        ],
        "PROMESA_PAGO": ["quiero pagar", "voy a pagar"],
        "QUIERE_ACUERDO": ["quiero hacer un acuerdo", "quiero llegar a un acuerdo"],
        "ACEPTA_ACUERDO": ["acepto el acuerdo", "me interesa el acuerdo"],
        "RECHAZA_ACUERDO": ["rechazo el acuerdo", "no quiero acuerdo"],
        "YA_PAGO": ["ya pague", "ya realice el pago"],
        "WHATSAPP_INFO": [
            "envieme por whatsapp",
            "mandeme la informacion",
            "por whatsapp",
            "quiero que me lo manden",
            "me lo puede mandar",
            "mandelo por whatsapp",
        ],
        "INTERRUPCION": [
            "espere",
            "un momento",
            "oiga",
            "disculpe",
            "pero",
            "dejeme hablar",
            "pare",
            "alto",
        ],
        "PREGUNTA_DEUDA": [
            "que deuda",
            "de que deuda",
            "cual deuda",
            "que me estan cobrando",
            "de que me habla",
            "con que banco",
            "que banco",
            "de que deuda me habla",
        ],
        "CONFIRMA_PERSONA": ["si soy", "soy yo", "digame", "le escucho", "escucho"],
        "DISPUTA_DEUDA": ["no reconozco esa deuda"],
        "NO_PUEDE_PAGAR": ["no puedo pagar"],
        "CALLBACK": ["llameme despues", "estoy ocupado"],
        "CALLBACK_MANANA": ["llameme manana", "manana me puede llamar", "mejor manana"],
        "ESTA_OCUPADO": ["ahora no puedo", "no puedo hablar", "llame despues"],
        "NUMERO_EQUIVOCADO": ["numero equivocado", "este no es su numero"],
        "NO_ES_PERSONA": ["no soy esa persona", "no la conozco"],
        "TERCERO": ["soy familiar", "soy tercero"],
        "FRAUDE_O_DESCONFIANZA": ["esto es fraude", "no confio"],
        "NO": [
            "no",
            "no quiero",
            "no me transfiera",
            "no me comuniquen",
            "no me pasen con cartera",
            "no quiero hablar",
            "no quiero hablar con asesor",
            "no quiero hablar con cartera",
            "no quiero saber de la deuda",
            "no llamen mas",
            "no autorizo",
            "no acepto",
        ],
        "DUDA": ["quien habla", "no entiendo", "repita"],
        "VULGARIDAD": [],
        "AMENAZA_VERBAL": [],
        "SILENCIO": [],
    }


def build_semantic_classifier_config() -> dict[str, object]:
    return {
        "enabled": True,
        "fuzzy_enabled": True,
        "semantic_enabled": False,
        "fuzzy_threshold": 0.78,
        "semantic_threshold": 0.72,
        "min_confidence": 0.70,
    }


def build_semantic_intents_config() -> dict[str, dict[str, list[str]]]:
    return {
        "TRANSFER_REQUEST": {
            "canonical": [
                "quiero hablar con un asesor",
                "me puede comunicar",
            ],
            "aliases": [
                "comunicame",
                "comunícame",
                "me comunica con un asesor",
                "quiero que me comuniquen",
                "quiero hablar con una persona",
                "me pueden pasar con un asesor",
                "me pasan con cartera",
                "paseme con cartera",
                "pasame con cartera",
                "quiero hablar con cartera",
                "me comunica con cartera",
                "comuniqueme con cartera",
            ],
        },
        "CALLBACK_MANANA": {
            "canonical": [
                "llameme manana",
                "manana me puede llamar",
            ],
            "aliases": [
                "mañana",
                "llámeme mañana",
                "mejor mañana",
                "hablemos mañana",
            ],
        },
        "WHATSAPP_INFO": {
            "canonical": [
                "envieme por whatsapp",
                "mandeme la informacion",
            ],
            "aliases": [
                "envíeme por WhatsApp",
                "mándeme la información",
                "por WhatsApp",
                "al WhatsApp",
                "envíemelo al WhatsApp",
                "quiero que me lo manden",
                "me lo puede mandar",
                "mándelo por WhatsApp",
                "mandelo por whatsapp",
            ],
        },
        "INTERRUPCION": {
            "canonical": [
                "espere",
                "dejeme hablar",
            ],
            "aliases": [
                "un momento",
                "oiga",
                "disculpe",
                "pero",
                "pare",
                "alto",
            ],
        },
        "PREGUNTA_DEUDA": {
            "canonical": [
                "que deuda",
                "de que deuda",
            ],
            "aliases": [
                "cual deuda",
                "que me estan cobrando",
                "de que me habla",
                "con que banco",
                "que banco",
                "de que deuda me habla",
            ],
        },
        "CONFIRMA_PERSONA": {
            "canonical": [
                "si soy",
                "soy yo",
            ],
            "aliases": [
                "digame",
                "le escucho",
                "escucho",
            ],
        },
        "ESTA_OCUPADO": {
            "canonical": [
                "ahora no puedo",
                "no puedo hablar",
            ],
            "aliases": [
                "estoy ocupado",
                "estoy trabajando",
                "llame despues",
            ],
        },
        "ACEPTA_ACUERDO": {
            "canonical": [
                "acepto el acuerdo",
                "me interesa el acuerdo",
            ],
            "aliases": [
                "si quiero un acuerdo",
                "si me interesa conversar",
                "acepto conversar",
            ],
        },
        "RECHAZA_ACUERDO": {
            "canonical": [
                "rechazo el acuerdo",
                "no quiero acuerdo",
            ],
            "aliases": [
                "no me interesa un acuerdo",
                "no me interesa conversar",
            ],
        },
        "NO": {
            "canonical": [
                "no quiero hablar",
                "no me transfiera",
            ],
            "aliases": [
                "no quiero que me comuniquen",
                "no quiero que me pasen",
                "no deseo hablar con asesor",
                "no me pasen con cartera",
                "no quiero hablar con cartera",
                "no quiero saber de la deuda",
            ],
        },
    }


def build_blocklist_matcher() -> BlocklistMatcher:
    return BlocklistMatcher.from_mapping(
        {
            "abusive_language": {
                "enabled": True,
                "terms": ["__ABUSIVE_TOKEN__"],
                "phrases": [],
            },
            "verbal_threats": {
                "enabled": True,
                "terms": ["__THREAT_TOKEN__"],
                "phrases": [],
            },
        }
    )


def test_normalize_text_removes_accents_and_punctuation() -> None:
    assert normalize_text("Sí, transfiérame.") == "si transfierame"


def test_tokenize_returns_token_list() -> None:
    assert tokenize("No   me transfiera 123") == ["no", "me", "transfiera", "123"]


@pytest.mark.parametrize(
    ("text", "phrase", "expected"),
    [
        ("silla rota", "si", False),
        ("noticia urgente", "no", False),
        ("sino", "si", False),
        ("sino", "no", False),
        ("no me transfiera", "no", True),
        ("quiero informacion de la deuda", "informacion de la deuda", True),
    ],
)
def test_contains_phrase_by_tokens_avoids_substring_false_positives(
    text: str,
    phrase: str,
    expected: bool,
) -> None:
    assert contains_phrase_by_tokens(text, phrase) is expected


@pytest.mark.parametrize(
    ("text", "expected_intent", "expected_phrase"),
    [
        ("no me transfiera", Intent.NO, "no me transfiera"),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO, "numero equivocado"),
        ("no soy esa persona", Intent.NO_ES_PERSONA, "no soy esa persona"),
        ("quiero informacion de la deuda", Intent.INFO_DEUDA, "quiero informacion de la deuda"),
        (
            "quiero saber cuanto es la deuda",
            Intent.INFO_DEUDA,
            "quiero saber cuanto es la deuda",
        ),
        ("me pasan con cartera", Intent.TRANSFER_REQUEST, "me pasan con cartera"),
        ("quiero pagar", Intent.PROMESA_PAGO, "quiero pagar"),
        ("quiero hacer un acuerdo", Intent.QUIERE_ACUERDO, "quiero hacer un acuerdo"),
        ("ya pague", Intent.YA_PAGO, "ya pague"),
        ("", Intent.SILENCIO, None),
    ],
)
def test_classify_intent_returns_expected_exact_match(
    text: str,
    expected_intent: Intent,
    expected_phrase: str | None,
) -> None:
    result = classify_intent(text, build_intents_config())

    assert isinstance(result, ClassifiedIntent)
    assert result.intent is expected_intent
    assert result.matched_phrase == expected_phrase


@pytest.mark.parametrize(
    "transcript",
    ["si", "sí", "claro"],
)
def test_classifies_simple_affirmatives_as_si(transcript: str) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is Intent.SI
    assert result.source == "transcript"
    assert result.confidence >= 0.8


@pytest.mark.parametrize(
    "transcript",
    [
        "comunicame",
        "comunícame",
        "me comunica con un asesor",
        "quiero que me comuniquen",
        "quiero hablar con una persona",
        "me pueden pasar con un asesor",
        "me pasan con cartera",
        "paseme con cartera",
        "pasame con cartera",
        "quiero hablar con cartera",
        "me comunica con cartera",
        "comuniqueme con cartera",
    ],
)
def test_classifies_transfer_request_phrases(transcript: str) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is Intent.TRANSFER_REQUEST
    assert result.source in {"transcript", "fuzzy"}
    assert result.confidence >= 0.78


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("quiero pagar", Intent.PROMESA_PAGO),
        ("quiero hacer un acuerdo", Intent.QUIERE_ACUERDO),
        ("ya pagué", Intent.YA_PAGO),
        ("cuánto debo", Intent.INFO_DEUDA),
        ("quiero información de la deuda", Intent.INFO_DEUDA),
        ("quiero saber cuanto es la deuda", Intent.INFO_DEUDA),
        ("quiero saber cuánto debo", Intent.INFO_DEUDA),
        ("cuánto es la deuda", Intent.INFO_DEUDA),
    ],
)
def test_classifies_cobranza_management_intents(
    transcript: str,
    expected_intent: Intent,
) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is expected_intent
    assert result.source == "transcript"


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("llámeme mañana", Intent.CALLBACK_MANANA),
        ("envíeme por WhatsApp", Intent.WHATSAPP_INFO),
        ("mándeme la información", Intent.WHATSAPP_INFO),
        ("por WhatsApp", Intent.WHATSAPP_INFO),
        ("quiero que me lo manden", Intent.WHATSAPP_INFO),
        ("me lo puede mandar", Intent.WHATSAPP_INFO),
        ("mándelo por WhatsApp", Intent.WHATSAPP_INFO),
        ("soy yo", Intent.CONFIRMA_PERSONA),
        ("ahora no puedo", Intent.ESTA_OCUPADO),
        ("acepto el acuerdo", Intent.ACEPTA_ACUERDO),
        ("rechazo el acuerdo", Intent.RECHAZA_ACUERDO),
    ],
)
def test_classifies_client_flow_stage_intents(
    transcript: str,
    expected_intent: Intent,
) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is expected_intent
    assert result.source in {"transcript", "fuzzy"}


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("espere", Intent.INTERRUPCION),
        ("déjeme hablar", Intent.INTERRUPCION),
        ("qué deuda", Intent.PREGUNTA_DEUDA),
        ("de qué deuda me habla", Intent.PREGUNTA_DEUDA),
    ],
)
def test_classifies_client_flow_stage_only_intents_when_stage_is_9912(
    transcript: str,
    expected_intent: Intent,
) -> None:
    result = build_classifier().classify(
        transcript=transcript,
        flow_stage="agreement_offer",
    )

    assert result.intent is expected_intent
    assert result.source in {"transcript", "fuzzy"}


@pytest.mark.parametrize("transcript", ["espere", "qué deuda", "de qué deuda me habla"])
def test_does_not_leak_client_flow_stage_only_intents_without_9912_stage(
    transcript: str,
) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is Intent.DUDA
    assert result.source == "default"


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("no", Intent.NO),
        ("no quiero", Intent.NO),
        ("no me comuniquen", Intent.NO),
        ("no me pasen con cartera", Intent.NO),
        ("no quiero hablar con asesor", Intent.NO),
        ("no quiero hablar con cartera", Intent.NO),
        ("no quiero saber de la deuda", Intent.NO),
        ("no me transfiera", Intent.NO),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO),
        ("no soy esa persona", Intent.NO_ES_PERSONA),
        ("soy familiar", Intent.TERCERO),
        ("llámeme después", Intent.CALLBACK),
        ("estoy ocupado", Intent.CALLBACK),
    ],
)
def test_classifies_non_transfer_intents_correctly(
    transcript: str,
    expected_intent: Intent,
) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is expected_intent
    assert result.source == "transcript"


def test_negative_intent_blocks_transfer_like_overlap() -> None:
    result = build_classifier().classify(transcript="no quiero que me comuniquen")

    assert result.intent is Intent.NO
    assert result.source in {"transcript", "fuzzy"}


def test_unknown_text_keeps_default_duda_confidence() -> None:
    result = build_classifier().classify(transcript="frase completamente desconocida")

    assert result.intent is Intent.DUDA
    assert result.source == "default"
    assert result.confidence == 0.35


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("__ABUSIVE_TOKEN__ sí", Intent.VULGARIDAD),
        ("__ABUSIVE_TOKEN__ comuníqueme", Intent.VULGARIDAD),
        ("__ABUSIVE_TOKEN__ envíeme por WhatsApp", Intent.VULGARIDAD),
        ("__THREAT_TOKEN__ quiero hablar", Intent.AMENAZA_VERBAL),
    ],
)
def test_blocklist_wins_over_transfer_intents(
    transcript: str,
    expected_intent: Intent,
) -> None:
    result = build_classifier().classify(transcript=transcript)

    assert result.intent is expected_intent
    assert result.source == "transcript"
    expected_match = "redacted[13]" if expected_intent is Intent.VULGARIDAD else "redacted[12]"
    assert result.matched_value == expected_match


def test_logs_fuzzy_classification_details(caplog: pytest.LogCaptureFixture) -> None:
    classifier = build_classifier()

    with caplog.at_level(logging.INFO):
        result = classifier.classify(transcript="comunicame")

    assert result.intent is Intent.TRANSFER_REQUEST
    assert any(
        "source=fuzzy" in record.message and "candidate=comunicame" in record.message
        for record in caplog.records
    )


def test_logs_blocklist_with_sanitized_match_only(caplog: pytest.LogCaptureFixture) -> None:
    classifier = build_classifier()

    with caplog.at_level(logging.INFO):
        result = classifier.classify(transcript="__ABUSIVE_TOKEN__ quiero hablar")

    assert result.intent is Intent.VULGARIDAD
    assert any("category=abusive_language" in record.message for record in caplog.records)
    assert all("__ABUSIVE_TOKEN__" not in record.message for record in caplog.records)


def test_classifies_dtmf_before_transcript() -> None:
    result = build_classifier().classify(transcript="no", dtmf="1")

    assert result.intent is Intent.SI
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


@pytest.mark.parametrize(
    ("transcript", "expected_intent"),
    [
        ("quiero hablar con una persona", Intent.TRANSFER_REQUEST),
        ("me pasan con cartera", Intent.TRANSFER_REQUEST),
        ("quiero pagar", Intent.PROMESA_PAGO),
        ("quiero hacer un acuerdo", Intent.QUIERE_ACUERDO),
        ("acepto el acuerdo", Intent.ACEPTA_ACUERDO),
        ("ya pague", Intent.YA_PAGO),
        ("quiero saber cuanto es la deuda", Intent.INFO_DEUDA),
        ("envíeme por WhatsApp", Intent.WHATSAPP_INFO),
        ("mándeme la información", Intent.WHATSAPP_INFO),
        ("por WhatsApp", Intent.WHATSAPP_INFO),
        ("no me comuniquen", Intent.NO),
        ("rechazo el acuerdo", Intent.RECHAZA_ACUERDO),
        ("no me pasen con cartera", Intent.NO),
        ("llámeme mañana", Intent.CALLBACK_MANANA),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO),
        ("soy familiar", Intent.TERCERO),
        ("soy yo", Intent.CONFIRMA_PERSONA),
        ("esto es fraude", Intent.FRAUDE_O_DESCONFIANZA),
    ],
)
def test_classifies_phrases_from_repo_yaml(
    transcript: str,
    expected_intent: Intent,
) -> None:
    intents = load_intents(Path("config/intents.yml"))
    classifier = IntentClassifier(
        phrases=intents,
        default_intent="DUDA",
        dtmf_map={},
        semantic_config=build_semantic_classifier_config(),
        semantic_intents=build_semantic_intents_config(),
    )

    result = classifier.classify(transcript=transcript)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    ("transcript", "flow_stage", "expected_intent"),
    [
        ("espere", "greeting_check", Intent.INTERRUPCION),
        ("déjeme hablar", "callback_offer", Intent.INTERRUPCION),
        ("qué deuda", "greeting_check", Intent.PREGUNTA_DEUDA),
        ("de qué deuda me habla", "agreement_offer", Intent.PREGUNTA_DEUDA),
    ],
)
def test_classifies_stage_only_phrases_from_repo_yaml_when_stage_matches(
    transcript: str,
    flow_stage: str,
    expected_intent: Intent,
) -> None:
    intents = load_intents(Path("config/intents.yml"))
    classifier = IntentClassifier(
        phrases=intents,
        default_intent="DUDA",
        dtmf_map={},
        semantic_config=build_semantic_classifier_config(),
        semantic_intents=build_semantic_intents_config(),
    )

    result = classifier.classify(transcript=transcript, flow_stage=flow_stage)

    assert result.intent is expected_intent


@pytest.mark.parametrize(
    ("partial", "expected_intent"),
    [
        ("si", Intent.SI),
        ("comuniqueme", Intent.TRANSFER_REQUEST),
        ("me pasan con cartera", Intent.TRANSFER_REQUEST),
        ("cuanto debo", Intent.INFO_DEUDA),
        ("quiero saber cuanto es la deuda", Intent.INFO_DEUDA),
        ("quiero pagar", Intent.PROMESA_PAGO),
        ("quiero hacer un acuerdo", Intent.QUIERE_ACUERDO),
        ("acepto el acuerdo", Intent.ACEPTA_ACUERDO),
        ("ya pague", Intent.YA_PAGO),
        ("no me transfiera", Intent.NO),
        ("no me pasen con cartera", Intent.NO),
        ("llameme manana", Intent.CALLBACK_MANANA),
        ("envieme por whatsapp", Intent.WHATSAPP_INFO),
        ("mandeme la informacion", Intent.WHATSAPP_INFO),
        ("por whatsapp", Intent.WHATSAPP_INFO),
        ("numero equivocado", Intent.NUMERO_EQUIVOCADO),
    ],
)
def test_detects_early_intent_from_partial(
    partial: str,
    expected_intent: Intent,
) -> None:
    match = detect_early_intent(
        partial,
        intents_config=build_intents_config(),
        blocklist_matcher=build_blocklist_matcher(),
    )

    assert match is not None
    assert match.intent is expected_intent


def test_detects_early_blocklist_before_transfer() -> None:
    match = detect_early_intent(
        "__THREAT_TOKEN__ quiero hablar",
        intents_config=build_intents_config(),
        blocklist_matcher=build_blocklist_matcher(),
    )

    assert match is not None
    assert match.intent is Intent.AMENAZA_VERBAL
    assert match.matched_value == "redacted[12]"


def test_does_not_detect_early_intent_on_substring_false_positive() -> None:
    assert detect_early_intent("silla", intents_config=build_intents_config()) is None


def test_early_detection_excludes_stage_only_intents_without_stage_context() -> None:
    assert detect_early_intent("que deuda", intents_config=build_intents_config()) is None
