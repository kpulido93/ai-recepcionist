from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "evaluate_intents.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location("scripts_evaluate_intents", SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
evaluate_intents = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = evaluate_intents
_SPEC.loader.exec_module(evaluate_intents)


def test_fixture_contains_at_least_sixty_cases() -> None:
    fixture_path = PROJECT_ROOT / "tests" / "fixtures" / "utterances_rd_cobranza.yml"

    cases = evaluate_intents.load_fixture(fixture_path)

    assert len(cases) >= 60
    assert any(case.expected_intent == "SI" for case in cases)
    assert any(case.expected_intent == "DUDA" for case in cases)


def test_evaluate_intents_script_runs_with_repo_fixture(capsys) -> None:
    exit_code = evaluate_intents.main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "accuracy_total:" in captured.out
    assert "accuracy_by_intent:" in captured.out
    assert "SI:" in captured.out
    assert "DUDA:" in captured.out


def test_evaluate_intents_script_passes_with_minimal_cases(
    tmp_path: Path,
    capsys,
) -> None:
    fixture_path = tmp_path / "fixture.yml"
    intents_path = tmp_path / "intents.yml"

    fixture_path.write_text(
        yaml.safe_dump(
            [
                {"text": "si", "expected_intent": "SI"},
                {"text": "no me transfiera", "expected_intent": "NO"},
                {"text": "silla", "expected_intent": "DUDA"},
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    intents_path.write_text(
        yaml.safe_dump(
            {
                "SI": ["si"],
                "NO": ["no", "no me transfiera"],
                "DUDA": ["quien habla"],
                "SILENCIO": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    exit_code = evaluate_intents.main(
        [
            "--fixture",
            str(fixture_path),
            "--intents",
            str(intents_path),
            "--threshold",
            "1.00",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "cases: 3" in captured.out
    assert "accuracy_total: 1.00" in captured.out
