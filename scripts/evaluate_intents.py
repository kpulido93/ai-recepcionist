#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
DEFAULT_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "utterances_rd_cobranza.yml"
DEFAULT_INTENTS_PATH = PROJECT_ROOT / "config" / "intents.yml"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


@dataclass(frozen=True)
class EvaluationCase:
    text: str
    expected_intent: str
    notes: str | None = None


@dataclass(frozen=True)
class EvaluationResult:
    case: EvaluationCase
    predicted_intent: str
    confidence: float
    matched_phrase: str | None
    normalized_text: str

    @property
    def passed(self) -> bool:
        return self.predicted_intent == self.case.expected_intent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evalua localmente el clasificador de intents con frases RD de cobranza."
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE_PATH,
        help="Ruta al fixture YAML de utterances",
    )
    parser.add_argument(
        "--intents",
        type=Path,
        default=DEFAULT_INTENTS_PATH,
        help="Ruta al intents.yml a evaluar",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="Accuracy total minima para salir con code 0",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from vicidial_vosk_cobranza_ivr.intent_classifier import (
        classify_intent,
        intent_value,
        load_intents,
        resolve_intent_name,
    )

    args = parse_args(argv)
    try:
        cases = load_fixture(args.fixture)
        intents = load_intents(args.intents)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    results: list[EvaluationResult] = []
    for case in cases:
        classified = classify_intent(case.text, intents)
        results.append(
            EvaluationResult(
                case=case,
                predicted_intent=intent_value(resolve_intent_name(classified.intent)),
                confidence=classified.confidence,
                matched_phrase=classified.matched_phrase,
                normalized_text=classified.normalized_text,
            )
        )

    print(f"fixture: {args.fixture}")
    print(f"intents: {args.intents}")
    print(f"cases: {len(results)}")
    print(f"threshold: {args.threshold:.2f}")
    total_accuracy = calculate_total_accuracy(results)
    print(f"accuracy_total: {total_accuracy:.2f}")
    print("accuracy_by_intent:")
    for intent_name, correct, total, accuracy in summarize_by_intent(results):
        print(f"  {intent_name}: {correct}/{total} ({accuracy:.2f})")

    failures = [result for result in results if not result.passed]
    if failures:
        print("failures:")
        for failure in failures:
            notes_fragment = f" notes={failure.case.notes}" if failure.case.notes else ""
            matched_phrase = failure.matched_phrase or "-"
            print(
                f"  expected={failure.case.expected_intent} "
                f"predicted={failure.predicted_intent} "
                f"confidence={failure.confidence:.2f} "
                f'matched_phrase={matched_phrase} text="{failure.case.text}"'
                f"{notes_fragment}"
            )

    return 0 if total_accuracy >= args.threshold else 1


def load_fixture(path: Path) -> list[EvaluationCase]:
    with path.open("r", encoding="utf-8") as file_handler:
        loaded = yaml.safe_load(file_handler) or []

    if not isinstance(loaded, list):
        raise ValueError(f"El fixture debe contener una lista de casos: {path}")

    cases: list[EvaluationCase] = []
    for index, item in enumerate(loaded, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Cada caso del fixture debe ser un objeto. Caso #{index}")

        text = item.get("text")
        expected_intent = item.get("expected_intent")
        notes = item.get("notes")

        if text is None or expected_intent is None:
            raise ValueError(
                f"Cada caso debe incluir text y expected_intent. Caso #{index}: {item}"
            )

        if notes is not None and not isinstance(notes, str):
            raise ValueError(f"notes debe ser string si existe. Caso #{index}: {item}")

        cases.append(
            EvaluationCase(
                text=str(text),
                expected_intent=str(expected_intent).strip().upper(),
                notes=notes,
            )
        )

    if not cases:
        raise ValueError(f"El fixture no contiene casos: {path}")

    return cases


def calculate_total_accuracy(results: list[EvaluationResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for result in results if result.passed) / len(results)


def summarize_by_intent(
    results: list[EvaluationResult],
) -> list[tuple[str, int, int, float]]:
    grouped: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in results:
        grouped[result.case.expected_intent].append(result)

    summary: list[tuple[str, int, int, float]] = []
    for intent_name in sorted(grouped):
        intent_results = grouped[intent_name]
        correct = sum(1 for result in intent_results if result.passed)
        total = len(intent_results)
        accuracy = correct / total if total else 0.0
        summary.append((intent_name, correct, total, accuracy))
    return summary


if __name__ == "__main__":
    raise SystemExit(main())
