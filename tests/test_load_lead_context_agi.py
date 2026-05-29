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
    module_path = Path(__file__).resolve().parents[1] / "agi" / "load_lead_context.py"
    spec = importlib.util.spec_from_file_location("load_lead_context_agi", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "lead_id,phone_number,client_name,client_gender,bank_name,portfolio_id,campaign_id,list_id",
                "1001,1001,Kevin,male,Banco Popular,popular_mora_30,LAB-CAMP,LAB-LIST",
                "2001,8095550201,Maria Ruiz,female,Banco Tres,CARTERA_C,CAMP_C,LIST_C",
            ]
        ),
        encoding="utf-8",
    )


def write_lab_leads_yaml(path: Path) -> None:
    path.write_text(
        """
lab_leads:
  "1001":
    lead_id: "lab-maiquer-caribe"
    nombre: "Maiquer"
    banco: "Banco Caribe"
    phone_number: "1001"
    client_gender: "male"
    portfolio_id: "caribe_lab"
    campaign_id: "LAB-OPTIMA"
    list_id: "LAB-1001"
""".strip(),
        encoding="utf-8",
    )


def test_load_lead_context_agi_sets_expected_variables(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)
    monkeypatch.setenv("IVR_LEAD_CONTEXT_CSV", str(csv_path))
    monkeypatch.setenv("IVR_LAB_LEADS_YML", str(tmp_path / "missing-lab-leads.yml"))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_LEAD_ID": "200 result=1 (2001)",
            "GET VARIABLE IVR_PHONE_NUMBER": "200 result=0",
            "GET VARIABLE CALLERID(num)": "200 result=0",
        }
    )

    exit_code = module.run_load_lead_context(session=session, environment={})

    assert exit_code == 0
    assert session.variables == {
        "IVR_CLIENT_NAME": "Maria Ruiz",
        "IVR_PERSON_NAME": "Maria Ruiz",
        "IVR_CLIENT_GENDER": "female",
        "IVR_BANK_NAME": "Banco Tres",
        "IVR_PORTFOLIO_ID": "CARTERA_C",
        "IVR_CAMPAIGN_ID": "CAMP_C",
        "IVR_LIST_ID": "LIST_C",
    }


def test_load_lead_context_agi_matches_by_callerid_when_phone_number_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)
    monkeypatch.setenv("IVR_LEAD_CONTEXT_CSV", str(csv_path))
    monkeypatch.setenv("IVR_LAB_LEADS_YML", str(tmp_path / "missing-lab-leads.yml"))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_LEAD_ID": "200 result=0",
            "GET VARIABLE IVR_PHONE_NUMBER": "200 result=0",
            "GET VARIABLE CALLERID(num)": "200 result=1 (1001)",
        }
    )

    exit_code = module.run_load_lead_context(session=session, environment={})

    assert exit_code == 0
    assert session.variables == {
        "IVR_CLIENT_NAME": "Kevin",
        "IVR_PERSON_NAME": "Kevin",
        "IVR_CLIENT_GENDER": "male",
        "IVR_BANK_NAME": "Banco Popular",
        "IVR_PORTFOLIO_ID": "popular_mora_30",
        "IVR_CAMPAIGN_ID": "LAB-CAMP",
        "IVR_LIST_ID": "LAB-LIST",
    }


def test_load_lead_context_agi_sets_empty_variables_when_not_found(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)
    monkeypatch.setenv("IVR_LEAD_CONTEXT_CSV", str(csv_path))
    monkeypatch.setenv("IVR_LAB_LEADS_YML", str(tmp_path / "missing-lab-leads.yml"))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_LEAD_ID": "200 result=1 (9999)",
            "GET VARIABLE IVR_PHONE_NUMBER": "200 result=0",
            "GET VARIABLE CALLERID(num)": "200 result=1 (8090000000)",
        }
    )

    exit_code = module.run_load_lead_context(session=session, environment={})

    assert exit_code == 0
    assert session.variables == {
        "IVR_CLIENT_NAME": "",
        "IVR_PERSON_NAME": "",
        "IVR_CLIENT_GENDER": "",
        "IVR_BANK_NAME": "",
        "IVR_PORTFOLIO_ID": "",
        "IVR_CAMPAIGN_ID": "",
        "IVR_LIST_ID": "",
    }


def test_load_lead_context_agi_resolves_lab_yaml_by_callerid(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    config_path.write_text(
        """
lead_context:
  csv_path: "leads.csv"
  lab_leads_path: "lab_leads.yml"
""".strip(),
        encoding="utf-8",
    )
    write_csv(tmp_path / "leads.csv")
    write_lab_leads_yaml(tmp_path / "lab_leads.yml")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_agi_module()
    session = FakeAgiSession(
        {
            "GET VARIABLE IVR_LEAD_ID": "200 result=0",
            "GET VARIABLE IVR_PHONE_NUMBER": "200 result=0",
            "GET VARIABLE CALLERID(num)": "200 result=1 (1001)",
        }
    )

    exit_code = module.run_load_lead_context(session=session, environment={})

    assert exit_code == 0
    assert session.variables["IVR_CLIENT_NAME"] == "Maiquer"
    assert session.variables["IVR_PERSON_NAME"] == "Maiquer"
    assert session.variables["IVR_BANK_NAME"] == "Banco Caribe"
