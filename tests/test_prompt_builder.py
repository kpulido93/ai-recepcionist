from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.prompt_builder import (
    build_bank_greeting_audio,
    build_cache_key,
    build_greeting_text,
    sanitize_prompt_value,
)

PROMPT_CONFIG = {
    "prompts": {
        "personalized_greeting_enabled": True,
        "greeting_template": (
            "Hola {client_name}, nos comunicamos de SokaCorp por una gestión pendiente "
            "relacionada con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
        ),
        "greeting_template_without_name": (
            "Hola, nos comunicamos de SokaCorp por una gestión pendiente relacionada con "
            "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
        ),
        "greeting_fallback": (
            "Hola, nos comunicamos de SokaCorp por una gestión pendiente. "
            "¿Desea que le comuniquemos ahora? Le escucho."
        ),
    }
}


def test_build_greeting_text_with_name_and_bank() -> None:
    text = build_greeting_text("Ana Perez", "Banco Uno", PROMPT_CONFIG)

    assert text == (
        "Hola Ana Perez, nos comunicamos de SokaCorp por una gestión pendiente relacionada "
        "con Banco Uno. ¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_greeting_text_without_name() -> None:
    text = build_greeting_text(None, "Banco Uno", PROMPT_CONFIG)

    assert text == (
        "Hola, nos comunicamos de SokaCorp por una gestión pendiente relacionada con Banco Uno. "
        "¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_greeting_text_without_bank_uses_fallback() -> None:
    text = build_greeting_text("Ana Perez", None, PROMPT_CONFIG)

    assert text == (
        "Hola, nos comunicamos de SokaCorp por una gestión pendiente. "
        "¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_greeting_text_fallback_when_personalization_disabled() -> None:
    config = {
        "prompts": {
            **PROMPT_CONFIG["prompts"],
            "personalized_greeting_enabled": False,
        }
    }

    text = build_greeting_text("Ana Perez", "Banco Uno", config)

    assert text == (
        "Hola, nos comunicamos de SokaCorp por una gestión pendiente. "
        "¿Desea que le comuniquemos ahora? Le escucho."
    )


def test_build_cache_key_is_stable() -> None:
    key = build_cache_key("123", "Ana Perez", "Banco Uno", "template-hash")

    assert key == build_cache_key("123", "Ana Perez", "Banco Uno", "template-hash")
    assert key != build_cache_key("123", "Ana Perez", "Banco Dos", "template-hash")
    assert key.startswith("greeting-123-")


def test_sanitize_prompt_value_removes_dangerous_values() -> None:
    text = sanitize_prompt_value('Ana "Demo";\n<script>')

    assert text == "Ana Demo script"


def test_build_bank_greeting_audio_returns_existing_asset(tmp_path: Path) -> None:
    sound_dir = tmp_path / "sounds"
    custom_dir = sound_dir / "custom"
    custom_dir.mkdir(parents=True)
    (custom_dir / "gestion-banco-uno.wav").write_bytes(b"wav")
    config = {
        "prompts": {
            "sound_search_dirs": [str(sound_dir)],
        }
    }

    playback_audio = build_bank_greeting_audio("Banco Uno", config)

    assert playback_audio == "custom/gestion-banco-uno"
