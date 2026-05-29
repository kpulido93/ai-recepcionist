from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.lead_context import (
    load_lead_context_from_csv,
    sanitize_lead_value,
)


def write_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "lead_id,phone_number,client_name,client_gender,bank_name,portfolio_id,campaign_id,list_id",
                "1001,809-555-0101,Ana Perez,female,Banco Uno,CARTERA_A,CAMP_A,LIST_A",
                "1002,+1 (809) 555-0102,Luis Gomez,male,Banco Dos,CARTERA_B,CAMP_B,LIST_B",
            ]
        ),
        encoding="utf-8",
    )


def test_load_lead_context_from_csv_matches_lead_id_first(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)

    context = load_lead_context_from_csv(
        csv_path,
        lead_id="1002",
        phone_number="8095550101",
    )

    assert context is not None
    assert context.client_name == "Luis Gomez"
    assert context.client_gender == "male"
    assert context.bank_name == "Banco Dos"
    assert context.portfolio_id == "CARTERA_B"


def test_load_lead_context_from_csv_matches_phone_number(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)

    context = load_lead_context_from_csv(csv_path, phone_number="18095550102")

    assert context is not None
    assert context.lead_id == "1002"
    assert context.client_gender == "male"
    assert context.campaign_id == "CAMP_B"
    assert context.list_id == "LIST_B"


def test_load_lead_context_from_csv_returns_none_when_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    write_csv(csv_path)

    context = load_lead_context_from_csv(csv_path, lead_id="9999", phone_number="8090000000")

    assert context is None


def test_sanitize_lead_value_limits_length_and_removes_dangerous_values() -> None:
    raw_value = 'Cliente "Demo"; rm -rf /\n<script>' + ("x" * 120)

    sanitized = sanitize_lead_value(raw_value, max_len=24)

    assert sanitized == "Cliente Demo rm -rf / sc"
    assert len(sanitized) == 24
    assert '"' not in sanitized
    assert ";" not in sanitized
    assert "\n" not in sanitized
    assert "<" not in sanitized
    assert ">" not in sanitized
