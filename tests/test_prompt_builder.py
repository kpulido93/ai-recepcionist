from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.config import PromptsSettings
from vicidial_vosk_cobranza_ivr.prompt_builder import (
    build_cache_key,
    build_greeting_text,
    generate_prompt_audio,
    sanitize_prompt_value,
)


def build_prompts_config(tmp_path: Path) -> PromptsSettings:
    return PromptsSettings(
        personalized_greeting_enabled=True,
        greeting_template=(
            "Hola {client_name}, nos comunicamos de SokaCorp por una gestion pendiente "
            "relacionada con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
        ),
        greeting_template_without_name=(
            "Hola, nos comunicamos de SokaCorp por una gestion pendiente relacionada con "
            "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
        ),
        greeting_fallback=(
            "Hola, nos comunicamos de SokaCorp por una gestion pendiente. "
            "¿Desea que le comuniquemos ahora? Le escucho."
        ),
        generated_audio_dir=str(tmp_path / "generated"),
        generated_audio_playback_prefix="custom/generated",
        tts_provider="espeak-ng",
        tts_voice="es-la",
        cache_enabled=True,
        privacy_mode=False,
        debug_log_values=False,
    )


def test_build_greeting_text_with_name_and_bank(tmp_path: Path) -> None:
    config = build_prompts_config(tmp_path)

    text = build_greeting_text("Juan Perez", "Banco Popular", config)

    assert text == (
        "Hola Juan Perez, nos comunicamos de SokaCorp por una gestion pendiente "
        "relacionada con Banco Popular. ¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_greeting_text_without_name(tmp_path: Path) -> None:
    config = build_prompts_config(tmp_path)

    text = build_greeting_text(None, "Banco BHD", config)

    assert text == (
        "Hola, nos comunicamos de SokaCorp por una gestion pendiente relacionada con "
        "Banco BHD. ¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_greeting_text_without_bank_uses_fallback(tmp_path: Path) -> None:
    config = build_prompts_config(tmp_path)

    text = build_greeting_text("Juan Perez", None, config)

    assert text == (
        "Hola, nos comunicamos de SokaCorp por una gestion pendiente. "
        "¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_sanitize_prompt_value_removes_dangerous_characters() -> None:
    sanitized = sanitize_prompt_value("Juan {Perez} / Banco<script> | rm -rf")

    assert "{" not in sanitized
    assert "}" not in sanitized
    assert "/" not in sanitized
    assert "|" not in sanitized
    assert "<" not in sanitized
    assert "script" in sanitized


def test_build_cache_key_is_stable() -> None:
    first_key = build_cache_key("12345", "Juan Perez", "Banco Popular", "abc123")
    second_key = build_cache_key("12345", "Juan Perez", "Banco Popular", "abc123")

    assert first_key == second_key
    assert first_key.startswith("lead-12345-greeting-")


def test_generate_prompt_audio_rejects_paths_outside_allowed_directory(tmp_path: Path) -> None:
    config = build_prompts_config(tmp_path)
    outside_path = tmp_path / "escape.wav"

    try:
        generate_prompt_audio("hola", outside_path, config)
    except ValueError as exc:
        assert "fuera del directorio permitido" in str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para una ruta fuera del directorio permitido")
