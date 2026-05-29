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


def build_client_flow_decision_engine() -> DecisionEngine:
    return DecisionEngine.from_mapping(
        {
            "defaults": {
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
                "CALLBACK_MANANA": {
                    "transfer_eligible": False,
                    "decision": "NO_TRANSFER",
                    "final_disposition": "VOZ_CALLBACK_MANANA",
                    "priority": 30,
                    "retry_allowed": False,
                    "hard_block": False,
                },
                "WHATSAPP_INFO": {
                    "transfer_eligible": False,
                    "decision": "NO_TRANSFER",
                    "final_disposition": "VOZ_WHATSAPP",
                    "priority": 40,
                    "retry_allowed": False,
                    "hard_block": False,
                },
                "NUMERO_EQUIVOCADO": {
                    "transfer_eligible": False,
                    "decision": "NO_TRANSFER",
                    "final_disposition": "VOZ_NUMERO_EQUIVOCADO",
                    "priority": 50,
                    "retry_allowed": False,
                    "hard_block": True,
                },
                "VULGARIDAD": {
                    "transfer_eligible": False,
                    "decision": "NO_TRANSFER",
                    "final_disposition": "VOZ_VULGARIDAD",
                    "priority": 60,
                    "retry_allowed": False,
                    "hard_block": True,
                },
            },
            "stages": {
                "greeting_check": {
                    "INTERRUPCION": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_INTERRUPCION_CONTINUA",
                        "priority": 8,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "PREGUNTA_DEUDA": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_PREGUNTA_DEUDA_CONTINUA",
                        "priority": 9,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "NO": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_NO_FINALIZA",
                        "priority": 9,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                    "SI": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_CONTINUA_GREETING",
                        "priority": 10,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "CONFIRMA_PERSONA": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_CONTINUA_GREETING",
                        "priority": 11,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "NUMERO_EQUIVOCADO": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_NUMERO_EQUIVOCADO",
                        "priority": 50,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                    "VULGARIDAD": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_VULGARIDAD",
                        "priority": 60,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                },
                "agreement_offer": {
                    "INTERRUPCION": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_INTERRUPCION_CONTINUA",
                        "priority": 18,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "PREGUNTA_DEUDA": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_PREGUNTA_DEUDA_CONTINUA",
                        "priority": 19,
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
                    "NO": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_NO_FINALIZA",
                        "priority": 21,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "WHATSAPP_INFO": {
                        "transfer_eligible": True,
                        "decision": "TRANSFER",
                        "final_disposition": "VOZ_WHATSAPP_TRANSFER",
                        "priority": 25,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "VULGARIDAD": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_VULGARIDAD",
                        "priority": 60,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                },
                "callback_offer": {
                    "INTERRUPCION": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_INTERRUPCION_CONTINUA",
                        "priority": 29,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "PREGUNTA_DEUDA": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_PREGUNTA_DEUDA_CONTINUA",
                        "priority": 30,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "CALLBACK_MANANA": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_CALLBACK_MANANA",
                        "priority": 30,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "WHATSAPP_INFO": {
                        "transfer_eligible": True,
                        "decision": "TRANSFER",
                        "final_disposition": "VOZ_WHATSAPP_TRANSFER",
                        "priority": 40,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "VULGARIDAD": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_VULGARIDAD",
                        "priority": 60,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                },
                "whatsapp_offer": {
                    "INTERRUPCION": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_INTERRUPCION_CONTINUA",
                        "priority": 39,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "PREGUNTA_DEUDA": {
                        "transfer_eligible": False,
                        "decision": "CONTINUE",
                        "final_disposition": "VOZ_PREGUNTA_DEUDA_CONTINUA",
                        "priority": 40,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "WHATSAPP_INFO": {
                        "transfer_eligible": True,
                        "decision": "TRANSFER",
                        "final_disposition": "VOZ_WHATSAPP_TRANSFER",
                        "priority": 40,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "NO": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_FINALIZA_EDUCADO",
                        "priority": 45,
                        "retry_allowed": False,
                        "hard_block": False,
                    },
                    "VULGARIDAD": {
                        "transfer_eligible": False,
                        "decision": "NO_TRANSFER",
                        "final_disposition": "VOZ_VULGARIDAD",
                        "priority": 60,
                        "retry_allowed": False,
                        "hard_block": True,
                    },
                },
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


def test_greeting_check_does_not_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.SI,
        confidence=0.95,
        transcript="si",
        matched_value="si",
        source="transcript",
        flow_stage="greeting_check",
    )

    assert result.decision == "CONTINUE"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_CONTINUA_GREETING"


def test_greeting_check_no_finishes_without_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.NO,
        confidence=0.95,
        transcript="no",
        matched_value="no",
        source="transcript",
        flow_stage="greeting_check",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_NO_FINALIZA"


@pytest.mark.parametrize(
    ("transcript", "intent"),
    [("soy yo", Intent.CONFIRMA_PERSONA), ("si soy", Intent.CONFIRMA_PERSONA)],
)
def test_greeting_check_confirma_persona_continues_without_transfer(
    transcript: str,
    intent: Intent,
) -> None:
    result = build_client_flow_decision_engine().decide(
        intent=intent,
        confidence=0.95,
        transcript=transcript,
        matched_value=transcript,
        source="transcript",
        flow_stage="greeting_check",
    )

    assert result.decision == "CONTINUE"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_CONTINUA_GREETING"


@pytest.mark.parametrize(
    ("intent", "transcript"),
    [
        (Intent.INTERRUPCION, "espere"),
        (Intent.PREGUNTA_DEUDA, "que deuda"),
    ],
)
def test_greeting_check_special_client_flow_intents_continue_without_transfer(
    intent: Intent,
    transcript: str,
) -> None:
    result = build_client_flow_decision_engine().decide(
        intent=intent,
        confidence=0.95,
        transcript=transcript,
        matched_value=transcript,
        source="transcript",
        flow_stage="greeting_check",
    )

    assert result.decision == "CONTINUE"
    assert result.transfer_eligible is False


def test_agreement_offer_transfers_transfer_request() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.TRANSFER_REQUEST,
        confidence=0.95,
        transcript="comunicame",
        matched_value="comunicame",
        source="transcript",
        flow_stage="agreement_offer",
    )

    assert result.decision == "TRANSFER"
    assert result.transfer_eligible is True
    assert result.final_disposition == "VOZ_TRANSFER_REQUEST"


def test_agreement_offer_no_finishes_without_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.NO,
        confidence=0.95,
        transcript="no",
        matched_value="no",
        source="transcript",
        flow_stage="agreement_offer",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_NO_FINALIZA"


def test_agreement_offer_question_about_debt_continues_without_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.PREGUNTA_DEUDA,
        confidence=0.95,
        transcript="que deuda",
        matched_value="que deuda",
        source="transcript",
        flow_stage="agreement_offer",
    )

    assert result.decision == "CONTINUE"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_PREGUNTA_DEUDA_CONTINUA"


def test_callback_offer_sets_callback_manana_without_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.CALLBACK_MANANA,
        confidence=0.95,
        transcript="llameme manana",
        matched_value="llameme manana",
        source="transcript",
        flow_stage="callback_offer",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_CALLBACK_MANANA"


@pytest.mark.parametrize(
    ("flow_stage", "transcript"),
    [
        ("agreement_offer", "envieme por whatsapp"),
        ("callback_offer", "envieme por whatsapp"),
        ("whatsapp_offer", "envieme por whatsapp"),
        ("whatsapp_offer", "mandeme la informacion"),
        ("whatsapp_offer", "por whatsapp"),
    ],
)
def test_whatsapp_info_transfers_in_client_flow_stages(
    flow_stage: str,
    transcript: str,
) -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.WHATSAPP_INFO,
        confidence=0.95,
        transcript=transcript,
        matched_value=transcript,
        source="transcript",
        flow_stage=flow_stage,
    )

    assert result.decision == "TRANSFER"
    assert result.transfer_eligible is True
    assert result.final_disposition == "VOZ_WHATSAPP_TRANSFER"


def test_no_in_whatsapp_offer_remains_non_transfer() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.NO,
        confidence=0.95,
        transcript="no",
        matched_value="no",
        source="transcript",
        flow_stage="whatsapp_offer",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.final_disposition == "VOZ_FINALIZA_EDUCADO"


@pytest.mark.parametrize(
    "flow_stage",
    ["greeting_check", "agreement_offer", "callback_offer", "whatsapp_offer"],
)
def test_vulgaridad_blocks_in_any_client_flow_stage(flow_stage: str) -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.VULGARIDAD,
        confidence=1.0,
        transcript="redacted",
        matched_value="redacted",
        source="transcript",
        flow_stage=flow_stage,
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.block_reason == "vulgaridad"


def test_numero_equivocado_finishes_on_greeting_check() -> None:
    result = build_client_flow_decision_engine().decide(
        intent=Intent.NUMERO_EQUIVOCADO,
        confidence=1.0,
        transcript="numero equivocado",
        matched_value="numero equivocado",
        source="transcript",
        flow_stage="greeting_check",
    )

    assert result.decision == "NO_TRANSFER"
    assert result.transfer_eligible is False
    assert result.block_reason == "numero_equivocado"
