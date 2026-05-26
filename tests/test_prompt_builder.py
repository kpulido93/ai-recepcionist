from __future__ import annotations

from pathlib import Path

import pytest

from vicidial_vosk_cobranza_ivr.prompt_builder import (
    build_bank_greeting_audio,
    build_cache_key,
    build_greeting_text,
    mirror_audio_file,
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


def test_mirror_audio_file_copies_source_into_all_target_dirs(tmp_path: Path) -> None:
    source_path = tmp_path / "source.wav"
    mirror_dir_one = tmp_path / "mirror-one"
    mirror_dir_two = tmp_path / "mirror-two"
    source_path.write_bytes(b"demo-audio")

    mirrored_paths = mirror_audio_file(
        source_path,
        [mirror_dir_one, mirror_dir_two],
    )

    assert mirrored_paths == [
        mirror_dir_one / "source.wav",
        mirror_dir_two / "source.wav",
    ]
    assert (mirror_dir_one / "source.wav").read_bytes() == b"demo-audio"
    assert (mirror_dir_two / "source.wav").read_bytes() == b"demo-audio"


def test_mirror_audio_file_uses_custom_filename_and_skips_duplicate_dirs(tmp_path: Path) -> None:
    source_path = tmp_path / "source.wav"
    mirror_dir = tmp_path / "mirror"
    source_path.write_bytes(b"demo-audio")

    mirrored_paths = mirror_audio_file(
        source_path,
        [mirror_dir, mirror_dir],
        filename="custom.wav",
    )

    assert mirrored_paths == [mirror_dir / "custom.wav"]
    assert (mirror_dir / "custom.wav").read_bytes() == b"demo-audio"


def test_mirror_audio_file_requires_existing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mirror_audio_file(tmp_path / "missing.wav", [tmp_path / "mirror"])
