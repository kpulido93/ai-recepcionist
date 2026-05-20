from __future__ import annotations

from vicidial_vosk_cobranza_ivr.logging_utils import mask_phone_numbers, mask_sensitive_data


def test_masks_phone_numbers_and_long_ids() -> None:
    message = "caller=3001234567 cedula=12345678901"

    masked = mask_sensitive_data(message)

    assert "3001234567" not in masked
    assert "12345678901" not in masked
    assert "XXXXXXXX67" in masked
    assert "XXXXXXXXX01" in masked


def test_masks_email_addresses() -> None:
    masked = mask_sensitive_data("correo=cliente.demo+1@empresa.com")

    assert masked == "correo=[EMAIL]"


def test_masks_amounts_with_currency_prefix_or_suffix() -> None:
    message = "deuda=$ 1,250.50 saldo=3500 pesos"

    masked = mask_sensitive_data(message)

    assert "$ 1,250.50" not in masked
    assert "3500 pesos" not in masked
    assert masked.count("[MONTO]") == 2


def test_masks_combined_sensitive_values() -> None:
    message = "llamar al +57 300 123 4567, correo juan@demo.co, cedula 12.345.678 y saldo USD 4500"

    masked = mask_sensitive_data(message)

    assert "+57 300 123 4567" not in masked
    assert "juan@demo.co" not in masked
    assert "12.345.678" not in masked
    assert "USD 4500" not in masked
    assert "[EMAIL]" in masked
    assert "[MONTO]" in masked


def test_mask_phone_numbers_hides_caller_value() -> None:
    masked = mask_phone_numbers("caller=3001234567")

    assert "3001234567" not in masked
    assert masked == "caller=XXXXXXXX67"
