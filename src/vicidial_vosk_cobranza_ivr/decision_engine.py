from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vicidial_vosk_cobranza_ivr.config import PROJECT_ROOT
from vicidial_vosk_cobranza_ivr.intent_classifier import (
    IntentName,
    intent_value,
    resolve_intent_name,
)

DEFAULT_SCENARIOS_PATH = PROJECT_ROOT / "config" / "scenarios.yml"
RETRYABLE_INTENTS = {"DUDA", "SILENCIO"}
BLOCK_REASON_INTENTS = {
    "AMENAZA_VERBAL",
    "CALLBACK",
    "FRAUDE_O_DESCONFIANZA",
    "NO",
    "NO_ES_PERSONA",
    "NUMERO_EQUIVOCADO",
    "TERCERO",
    "VULGARIDAD",
}


@dataclass(frozen=True)
class ScenarioRule:
    transfer_eligible: bool
    decision: str
    final_disposition: str
    priority: int
    retry_allowed: bool
    hard_block: bool


@dataclass(frozen=True)
class DecisionOutcome:
    decision: str
    transfer_eligible: bool
    block_reason: str | None
    final_disposition: str
    reason: str


class DecisionEngine:
    def __init__(self, scenarios: Mapping[str, ScenarioRule]) -> None:
        self.scenarios = dict(scenarios)

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_SCENARIOS_PATH) -> DecisionEngine:
        with path.open("r", encoding="utf-8") as file_handler:
            loaded = yaml.safe_load(file_handler) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError(f"La matriz de escenarios debe ser un objeto YAML: {path}")
        return cls(build_scenarios(loaded))

    @classmethod
    def from_mapping(cls, raw_scenarios: Mapping[str, Any]) -> DecisionEngine:
        return cls(build_scenarios(raw_scenarios))

    def decide(
        self,
        *,
        intent: IntentName,
        confidence: float,
        transcript: str,
        matched_value: str | None,
        source: str,
        retry_count: int = 0,
    ) -> DecisionOutcome:
        del confidence, transcript, matched_value, source

        intent_name = intent_value(resolve_intent_name(intent))
        rule = self.scenarios.get(intent_name)
        if rule is None:
            return DecisionOutcome(
                decision="NO_TRANSFER",
                transfer_eligible=False,
                block_reason="intent_not_configured",
                final_disposition="VOZ_INTENT_NO_CONFIGURADO",
                reason=f"intent={intent_name} scenario=missing",
            )

        if rule.decision == "RETRY":
            return _build_retry_outcome(intent_name=intent_name, rule=rule, retry_count=retry_count)

        if rule.decision == "TRANSFER":
            return DecisionOutcome(
                decision="TRANSFER",
                transfer_eligible=True,
                block_reason=None,
                final_disposition=rule.final_disposition,
                reason=f"intent={intent_name} scenario=transfer",
            )

        block_reason = _build_block_reason(intent_name, rule)
        return DecisionOutcome(
            decision="NO_TRANSFER",
            transfer_eligible=False,
            block_reason=block_reason,
            final_disposition=rule.final_disposition,
            reason=f"intent={intent_name} scenario=no_transfer",
        )


def build_scenarios(raw_scenarios: Mapping[str, Any]) -> dict[str, ScenarioRule]:
    scenarios: dict[str, ScenarioRule] = {}
    for raw_intent_name, raw_rule in raw_scenarios.items():
        if not isinstance(raw_rule, Mapping):
            continue
        intent_name = intent_value(resolve_intent_name(str(raw_intent_name)))
        scenarios[intent_name] = ScenarioRule(
            transfer_eligible=bool(raw_rule.get("transfer_eligible", False)),
            decision=str(raw_rule.get("decision", "NO_TRANSFER")).upper(),
            final_disposition=str(raw_rule.get("final_disposition", "VOZ_SIN_DECISION")),
            priority=int(raw_rule.get("priority", 0)),
            retry_allowed=bool(raw_rule.get("retry_allowed", False)),
            hard_block=bool(raw_rule.get("hard_block", False)),
        )
    return scenarios


def _build_retry_outcome(
    *,
    intent_name: str,
    rule: ScenarioRule,
    retry_count: int,
) -> DecisionOutcome:
    should_retry = rule.retry_allowed and retry_count <= 0 and intent_name in RETRYABLE_INTENTS
    if should_retry:
        return DecisionOutcome(
            decision="RETRY",
            transfer_eligible=False,
            block_reason=None,
            final_disposition=rule.final_disposition,
            reason=f"intent={intent_name} scenario=retry",
        )

    return DecisionOutcome(
        decision="HANGUP",
        transfer_eligible=False,
        block_reason="retry_exhausted" if intent_name in RETRYABLE_INTENTS else None,
        final_disposition=rule.final_disposition,
        reason=f"intent={intent_name} scenario=retry_exhausted",
    )


def _build_block_reason(intent_name: str, rule: ScenarioRule) -> str | None:
    if rule.hard_block or intent_name in BLOCK_REASON_INTENTS:
        return intent_name.lower()
    return None
