from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.routing import load_routing_config, resolve_transfer_target


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def build_routing_config(tmp_path: Path, *, dangerous_bhd_target: bool = False):
    routing_path = tmp_path / "routing.yml"
    bhd_target = "PJSIP/1003"
    if dangerous_bhd_target:
        bhd_target = "PJSIP/1003;System(rm -rf /)"

    write_text(
        routing_path,
        f"""
default_transfer_target: "PJSIP/1002"
portfolios:
  banco_popular:
    bank_names:
      - "Banco Popular"
      - "Popular"
    transfer_target: "PJSIP/1002"
  banco_bhd:
    bank_names:
      - "Banco BHD"
      - "BHD"
    transfer_target: "{bhd_target}"
""".strip(),
    )
    return load_routing_config(routing_path)


def test_resolve_transfer_target_for_banco_popular(tmp_path: Path) -> None:
    config = build_routing_config(tmp_path)

    target = resolve_transfer_target(bank_name="Banco Popular", config=config)

    assert target == "PJSIP/1002"


def test_resolve_transfer_target_for_bhd(tmp_path: Path) -> None:
    config = build_routing_config(tmp_path)

    target = resolve_transfer_target(bank_name="BHD", config=config)

    assert target == "PJSIP/1003"


def test_resolve_transfer_target_uses_default_for_unknown_bank(tmp_path: Path) -> None:
    config = build_routing_config(tmp_path)

    target = resolve_transfer_target(bank_name="Banco Desconocido", config=config)

    assert target == "PJSIP/1002"


def test_portfolio_id_wins_over_bank_name_when_present(tmp_path: Path) -> None:
    config = build_routing_config(tmp_path)

    target = resolve_transfer_target(
        bank_name="Banco Popular",
        portfolio_id="banco_bhd",
        config=config,
    )

    assert target == "PJSIP/1003"


def test_dangerous_transfer_target_falls_back_to_default(tmp_path: Path) -> None:
    config = build_routing_config(tmp_path, dangerous_bhd_target=True)

    target = resolve_transfer_target(bank_name="BHD", config=config)

    assert target == "PJSIP/1002"
