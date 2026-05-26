from __future__ import annotations

import sys

from vicidial_vosk_cobranza_ivr.blocklist import BlocklistMatcher
from vicidial_vosk_cobranza_ivr.config import load_app_config, resolve_runtime_paths
from vicidial_vosk_cobranza_ivr.decision_engine import DecisionEngine
from vicidial_vosk_cobranza_ivr.intent_classifier import IntentClassifier, normalize_text


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print('uso: python scripts/test_intent_matrix.py "comunicame"')
        return 1

    transcript = argv[1]
    runtime_paths = resolve_runtime_paths()
    config = load_app_config(runtime_paths.config_path, runtime_paths.intents_path)
    classifier = IntentClassifier(
        phrases=config.intents,
        default_intent=config.ivr.default_intent,
        dtmf_map=config.ivr.dtmf_map,
        semantic_config={
            "enabled": config.semantic_classifier.enabled,
            "fuzzy_enabled": config.semantic_classifier.fuzzy_enabled,
            "semantic_enabled": config.semantic_classifier.semantic_enabled,
            "fuzzy_threshold": config.semantic_classifier.fuzzy_threshold,
            "semantic_threshold": config.semantic_classifier.semantic_threshold,
            "min_confidence": config.semantic_classifier.min_confidence,
        },
        semantic_intents=config.semantic_intents,
        blocklist_matcher=BlocklistMatcher.from_paths(),
    )
    decision_engine = DecisionEngine.from_yaml()

    classification = classifier.classify(transcript=transcript)
    decision = decision_engine.decide(
        intent=classification.intent,
        confidence=classification.confidence,
        transcript=classification.transcript,
        matched_value=classification.matched_value,
        source=classification.source,
    )

    print(f"transcript original: {transcript}")
    print(f"transcript normalizado: {normalize_text(transcript)}")
    print(f"intent: {classification.intent}")
    print(f"confidence: {classification.confidence:.2f}")
    print(f"source: {classification.source}")
    print(f"matched_value: {classification.matched_value or ''}")
    print(f"decision: {decision.decision}")
    print(f"transfer_eligible: {int(decision.transfer_eligible)}")
    print(f"block_reason: {decision.block_reason or ''}")
    print(f"final_disposition: {decision.final_disposition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
