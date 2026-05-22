from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.routing import load_routing_config, resolve_transfer_target


def write_routing_config(path: Path) -> None:
    path.write_text(
        """
default_transfer_target: "PJSIP/1002"
allowed_target_patterns:
  - "^PJSIP/[A-Za-z0-9_-]+$"
  - "^Local/[A-Za-z0-9_-]+@[A-Za-z0-9_-]+$"

portfolios:
  popular_mora_30:
    bank_names:
      - "Banco Popular"
      - "Popular"
    transfer_target: "PJSIP/1002"

  bhd_mora_60:
    bank_names:
      - "Banco BHD"
      - "BHD"
    transfer_target: "PJSIP/1003"

  cartera_peligrosa:
    bank_names:
      - "Banco Riesgo"
    transfer_target: "PJSIP/1004&System(rm -rf /)"
""".strip(),
        encoding="utf-8",
    )


def test_resolve_transfer_target_matches_portfolio_id(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    config = load_routing_config(routing_path)

    target = resolve_transfer_target(portfolio_id=" Popular Mora 30 ", config=config)

    assert target == "PJSIP/1002"


def test_resolve_transfer_target_matches_bank_name(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    config = load_routing_config(routing_path)

    target = resolve_transfer_target(bank_name="banco BHD", config=config)

    assert target == "PJSIP/1003"


def test_resolve_transfer_target_returns_default_for_unknown_portfolio(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    config = load_routing_config(routing_path)

    target = resolve_transfer_target(portfolio_id="desconocida", config=config)

    assert target == "PJSIP/1002"


def test_resolve_transfer_target_rejects_dangerous_target(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    config = load_routing_config(routing_path)

    target = resolve_transfer_target(portfolio_id="cartera_peligrosa", config=config)

    assert target == "PJSIP/1002"


def test_resolve_transfer_target_prefers_portfolio_id_over_bank_name(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    write_routing_config(routing_path)
    config = load_routing_config(routing_path)

    target = resolve_transfer_target(
        portfolio_id="popular_mora_30",
        bank_name="Banco BHD",
        config=config,
    )

    assert target == "PJSIP/1002"
