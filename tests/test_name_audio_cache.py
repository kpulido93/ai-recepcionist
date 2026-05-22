from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr import name_audio_cache
from vicidial_vosk_cobranza_ivr.name_audio_cache import (
    build_name_cache_key,
    get_cached_name_audio,
    get_or_generate_name_audio,
    normalize_person_name,
    safe_slug,
)


def build_config(tmp_path: Path) -> dict[str, object]:
    return {
        "name_audio": {
            "enabled": True,
            "provider": "elevenlabs",
            "cache_enabled": True,
            "cache_dir": str(tmp_path / "names"),
            "mirror_dirs": [],
            "playback_prefix": "custom/generated/names",
            "version": "v1",
            "max_name_chars": 80,
            "fallback_on_error": True,
            "elevenlabs": {
                "api_key_env": "ELEVENLABS_API_KEY",
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "output_format": "wav",
                "timeout_seconds": 15,
            },
        }
    }


def test_normalize_person_name_removes_weird_spaces_and_dangerous_chars() -> None:
    name = '  Juan\u200b  "Pérez"; ../../ \n'

    normalized = normalize_person_name(name)

    assert normalized == "Juan Pérez .. .."


def test_safe_slug_rejects_path_traversal() -> None:
    slug = safe_slug("../../Juan Pérez")

    assert slug == "juan-perez"
    assert "/" not in slug
    assert ".." not in slug


def test_build_name_cache_key_changes_with_provider_version_inputs() -> None:
    first = build_name_cache_key("Juan Pérez", "voice-a", "model-a", "v1")
    second = build_name_cache_key("Juan Pérez", "voice-b", "model-a", "v1")
    third = build_name_cache_key("Juan Pérez", "voice-a", "model-b", "v1")
    fourth = build_name_cache_key("Juan Pérez", "voice-a", "model-a", "v2")

    assert first != second
    assert first != third
    assert first != fourth


def test_get_cached_name_audio_returns_existing_file(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["name_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    cache_key = build_name_cache_key("Juan Pérez", "voice-demo", "model-demo", "v1")
    output_path = cache_dir / f"{cache_key}.wav"
    output_path.write_bytes(b"wav")

    cached_path = get_cached_name_audio("Juan Pérez", config)

    assert cached_path == output_path


def test_get_or_generate_name_audio_uses_cache_without_calling_provider(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["name_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    cache_key = build_name_cache_key("Juan Pérez", "voice-demo", "model-demo", "v1")
    output_path = cache_dir / f"{cache_key}.wav"
    output_path.write_bytes(b"wav")

    def fail_generate(name: str, config_data: dict[str, object]) -> Path:
        raise AssertionError("generate_name_audio no debe llamarse si ya existe cache")

    monkeypatch.setattr(name_audio_cache, "generate_name_audio", fail_generate)

    cached_path = get_or_generate_name_audio("Juan Pérez", config)

    assert cached_path == output_path


def test_get_or_generate_name_audio_returns_none_when_api_key_is_missing(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    generated_path = get_or_generate_name_audio("Juan Pérez", config)

    assert generated_path is None
