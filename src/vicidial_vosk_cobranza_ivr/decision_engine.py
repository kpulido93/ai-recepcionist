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
DEFAULT_SCENARIOS_SECTION_KEY = "defaults"
STAGE_SCENARIOS_SECTION_KEY = "stages"
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
    def __init__(
        self,
        scenarios: Mapping[str, ScenarioRule],
        stage_scenarios: Mapping[str, Mapping[str, ScenarioRule]] | None = None,
    ) -> None:
        self.scenarios = dict(scenarios)
        self.stage_scenarios = {
            normalize_flow_stage(flow_stage): dict(stage_rules)
            for flow_stage, stage_rules in (stage_scenarios or {}).items()
        }

    @classmethod
    def from_yaml(cls, path: Path = DEFAULT_SCENARIOS_PATH) -> DecisionEngine:
        with path.open("r", encoding="utf-8") as file_handler:
            loaded = yaml.safe_load(file_handler) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError(f"La matriz de escenarios debe ser un objeto YAML: {path}")
        raw_default_scenarios, raw_stage_scenarios = _split_scenarios_config(loaded)
        return cls(
            build_scenarios(raw_default_scenarios),
            build_stage_scenarios(raw_stage_scenarios),
        )

    @classmethod
    def from_mapping(cls, raw_scenarios: Mapping[str, Any]) -> DecisionEngine:
        raw_default_scenarios, raw_stage_scenarios = _split_scenarios_config(raw_scenarios)
        return cls(
            build_scenarios(raw_default_scenarios),
            build_stage_scenarios(raw_stage_scenarios),
        )

    def decide(
        self,
        *,
        intent: IntentName,
        confidence: float,
        transcript: str,
        matched_value: str | None,
        source: str,
        retry_count: int = 0,
        flow_stage: str | None = None,
    ) -> DecisionOutcome:
        del confidence, transcript, matched_value, source

        intent_name = intent_value(resolve_intent_name(intent))
        rule = self._resolve_rule(intent_name, flow_stage=flow_stage)
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

        block_reason = None
        if rule.decision in {"NO_TRANSFER", "HANGUP"}:
            block_reason = _build_block_reason(intent_name, rule)
        return DecisionOutcome(
            decision=rule.decision,
            transfer_eligible=False,
            block_reason=block_reason,
            final_disposition=rule.final_disposition,
            reason=f"intent={intent_name} scenario=no_transfer",
        )

    def _resolve_rule(self, intent_name: str, *, flow_stage: str | None) -> ScenarioRule | None:
        normalized_stage = normalize_flow_stage(flow_stage)
        if normalized_stage:
            stage_rule = self.stage_scenarios.get(normalized_stage, {}).get(intent_name)
            if stage_rule is not None:
                return stage_rule
        return self.scenarios.get(intent_name)


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


def build_stage_scenarios(
    raw_stage_scenarios: Mapping[str, Any],
) -> dict[str, dict[str, ScenarioRule]]:
    scenarios: dict[str, dict[str, ScenarioRule]] = {}
    for raw_stage_name, raw_stage_rules in raw_stage_scenarios.items():
        if not isinstance(raw_stage_rules, Mapping):
            continue
        normalized_stage_name = normalize_flow_stage(raw_stage_name)
        if not normalized_stage_name:
            continue
        scenarios[normalized_stage_name] = build_scenarios(raw_stage_rules)
    return scenarios


def normalize_flow_stage(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _split_scenarios_config(
    raw_config: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if DEFAULT_SCENARIOS_SECTION_KEY in raw_config or STAGE_SCENARIOS_SECTION_KEY in raw_config:
        raw_default_scenarios = raw_config.get(DEFAULT_SCENARIOS_SECTION_KEY, {})
        raw_stage_scenarios = raw_config.get(STAGE_SCENARIOS_SECTION_KEY, {})
        if not isinstance(raw_default_scenarios, Mapping):
            raise ValueError("La sección defaults de escenarios debe ser un objeto YAML.")
        if not isinstance(raw_stage_scenarios, Mapping):
            raise ValueError("La sección stages de escenarios debe ser un objeto YAML.")
        return raw_default_scenarios, raw_stage_scenarios

    return raw_config, {}


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
