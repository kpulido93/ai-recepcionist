from __future__ import annotations

import pytest

from vicidial_vosk_cobranza_ivr.decision_engine import DecisionEngine
from vicidial_vosk_cobranza_ivr.intent_classifier import Intent


def build_decision_engine() -> DecisionEngine:
    return DecisionEngine.from_mapping(
        {
            "SI": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_SI_ABOGADO",
                "priority": 10,
                "retry_allowed": False,
                "hard_block": False,
            },
            "TRANSFER_REQUEST": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_TRANSFER_REQUEST",
                "priority": 20,
                "retry_allowed": False,
                "hard_block": False,
            },
            "INFO_COBRO": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_INFO_COBRO",
                "priority": 30,
                "retry_allowed": False,
                "hard_block": False,
            },
            "INFO_DEUDA": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_INFO_DEUDA",
                "priority": 40,
                "retry_allowed": False,
                "hard_block": False,
            },
            "PROMESA_PAGO": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_PROMESA_PAGO",
                "priority": 50,
                "retry_allowed": False,
                "hard_block": False,
            },
            "QUIERE_ACUERDO": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_QUIERE_ACUERDO",
                "priority": 60,
                "retry_allowed": False,
                "hard_block": False,
            },
            "YA_PAGO": {
                "transfer_eligible": True,
                "decision": "TRANSFER",
                "final_disposition": "VOZ_YA_PAGO",
                "priority": 70,
                "retry_allowed": False,
                "hard_block": False,
            },
            "NO": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_NO_FINALIZA",
                "priority": 80,
                "retry_allowed": False,
                "hard_block": True,
            },
            "NUMERO_EQUIVOCADO": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_NUMERO_EQUIVOCADO",
                "priority": 90,
                "retry_allowed": False,
                "hard_block": True,
            },
            "NO_ES_PERSONA": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_NO_ES_PERSONA",
                "priority": 95,
                "retry_allowed": False,
                "hard_block": True,
            },
            "TERCERO": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_TERCERO",
                "priority": 96,
                "retry_allowed": False,
                "hard_block": True,
            },
            "CALLBACK": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_CALLBACK",
                "priority": 97,
                "retry_allowed": False,
                "hard_block": False,
            },
            "VULGARIDAD": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_VULGARIDAD",
                "priority": 98,
                "retry_allowed": False,
                "hard_block": True,
            },
            "AMENAZA_VERBAL": {
                "transfer_eligible": False,
                "decision": "NO_TRANSFER",
                "final_disposition": "VOZ_AMENAZA_VERBAL",
                "priority": 99,
                "retry_allowed": False,
                "hard_block": True,
            },
            "DUDA": {
                "transfer_eligible": False,
                "decision": "RETRY",
                "final_disposition": "VOZ_DUDA",
                "priority": 5,
                "retry_allowed": True,
                "hard_block": False,
            },
            "SILENCIO": {
                "transfer_eligible": False,
                "decision": "RETRY",
                "final_disposition": "VOZ_SILENCIO",
                "priority": 1,
                "retry_allowed": True,
                "hard_block": False,
            },
        }
    )


@pytest.mark.parametrize(
    ("intent", "expected_disposition"),
    [
        (Intent.SI, "VOZ_SI_ABOGADO"),
        (Intent.TRANSFER_REQUEST, "VOZ_TRANSFER_REQUEST"),
        (Intent.INFO_COBRO, "VOZ_INFO_COBRO"),
        (Intent.INFO_DEUDA, "VOZ_INFO_DEUDA"),
        (Intent.PROMESA_PAGO, "VOZ_PROMESA_PAGO"),
        (Intent.QUIERE_ACUERDO, "VOZ_QUIERE_ACUERDO"),
        (Intent.YA_PAGO, "VOZ_YA_PAGO"),
    ],
)
def test_transfer_intents_return_transfer(
    intent: Intent,
    expected_disposition: str,
) -> None:
    result = build_decision_engine().decide(
        intent=intent,
        confidence=0.91,
        transcript="demo",
        matched_value="demo",
        source="transcript",
    )

    assert result.decision == "TRANSFER"
    assert result.transfer_eligible is True
    assert result.block_reason is None
    assert result.final_disposition == expected_disposition


@pytest.mark.parametrize(
    ("intent", "expected_block_reason"),
    [
        (Intent.NO, "no"),
        (Intent.NUMERO_EQUIVOCADO, "numero_equivocado"),
        (Intent.NO_ES_PERSONA, "no_es_persona"),
        (Intent.TERCERO, "tercero"),
        (Intent.CALLBACK, "callback"),
        (Intent.VULGARIDAD, "vulgaridad"),
        (Intent.AMENAZA_VERBAL, "amenaza_verbal"),
    ],
)
def test_non_transfer_intents_return_no_transfer(
    intent: Intent,
    expected_block_reason: str,
) -> None:
    result = build_decision_engine().decide(
        intent=intent,
        confidence=0.95,
        transcript="demo",
        matched_value="demo",
        source="transcript",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.block_reason == expected_block_reason


def test_duda_retries_once() -> None:
    engine = build_decision_engine()

    first = engine.decide(
        intent=Intent.DUDA,
        confidence=0.35,
        transcript="no entiendo",
        matched_value="no entiendo",
        source="transcript",
        retry_count=0,
    )
    second = engine.decide(
        intent=Intent.DUDA,
        confidence=0.35,
        transcript="no entiendo",
        matched_value="no entiendo",
        source="transcript",
        retry_count=1,
    )

    assert first.decision == "RETRY"
    assert second.decision == "HANGUP"
    assert second.block_reason == "retry_exhausted"


def test_silencio_retries_once_then_hangup() -> None:
    engine = build_decision_engine()

    first = engine.decide(
        intent=Intent.SILENCIO,
        confidence=0.0,
        transcript="",
        matched_value=None,
        source="silence",
        retry_count=0,
    )
    second = engine.decide(
        intent=Intent.SILENCIO,
        confidence=0.0,
        transcript="",
        matched_value=None,
        source="silence",
        retry_count=1,
    )

    assert first.decision == "RETRY"
    assert second.decision == "HANGUP"


def test_missing_scenario_falls_back_to_safe_no_transfer() -> None:
    result = build_decision_engine().decide(
        intent="CUSTOM",
        confidence=0.80,
        transcript="demo",
        matched_value="demo",
        source="default",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.block_reason == "intent_not_configured"
