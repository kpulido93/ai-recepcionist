from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


class FakeAgiSession:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.commands: list[str] = []
        self.variables: dict[str, str] = {}

    def command(self, command_line: str) -> str:
        self.commands.append(command_line)
        return self.responses.get(command_line, "200 result=0")

    def set_variable(self, name: str, value: str) -> str:
        self.variables[name] = value
        return "200 result=1"


def load_agi_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "agi" / "resolve_transfer_target.py"
    spec = importlib.util.spec_from_file_location("resolve_transfer_target_agi", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_routing_config(path: Path) -> None:
    path.write_text(
        """
default_transfer_target: "PJSIP/1002"
allowed_target_patterns:
  - "^PJSIP/[A-Za-z0-9_-]+$"

portfolios:
  bhd_mora_60:
    bank_names:
      - "Banco BHD"
      - "BHD"
    transfer_target: "PJSIP/1003"
""".strip(),
        encoding="utf-8",
    )


def test_resolve_transfer_target_agi_sets_ivr_transfer_target(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    monkeypatch.setenv("IVR_ROUTING_CONFIG", str(routing_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_PORTFOLIO_ID": "200 result=0",
            "GET VARIABLE IVR_BANK_NAME": "200 result=1 (Banco BHD)",
        }
    )

    exit_code = module.run_resolve_transfer_target(session=session, environment={})

    assert exit_code == 0
    assert session.variables == {"IVR_TRANSFER_TARGET": "PJSIP/1003"}
