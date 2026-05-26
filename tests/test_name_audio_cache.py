from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr import name_audio_cache
from vicidial_vosk_cobranza_ivr.name_audio_cache import (
    build_name_audio_text,
    build_name_cache_key,
    get_cached_name_audio,
    get_or_generate_name_audio,
    normalize_name_audio_gender,
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
            "mirror_dirs": [str(tmp_path / "mirror")],
            "playback_prefix": "custom/generated/names",
            "version": "v1",
            "max_name_chars": 80,
            "fallback_on_error": True,
            "templates": {
                "male": "Señor {name},",
                "female": "Señora {name},",
                "unknown": "{name},",
            },
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
    first = build_name_cache_key(
        "Juan Pérez",
        "voice-a",
        "model-a",
        "v1",
        gender="male",
        final_text="Señor Juan Pérez,",
    )
    second = build_name_cache_key(
        "Juan Pérez",
        "voice-b",
        "model-a",
        "v1",
        gender="male",
        final_text="Señor Juan Pérez,",
    )
    third = build_name_cache_key(
        "Juan Pérez",
        "voice-a",
        "model-b",
        "v1",
        gender="male",
        final_text="Señor Juan Pérez,",
    )
    fourth = build_name_cache_key(
        "Juan Pérez",
        "voice-a",
        "model-a",
        "v2",
        gender="male",
        final_text="Señor Juan Pérez,",
    )
    fifth = build_name_cache_key(
        "Juan Pérez",
        "voice-a",
        "model-a",
        "v1",
        gender="female",
        final_text="Señora Juan Pérez,",
    )

    assert first != second
    assert first != third
    assert first != fourth
    assert first != fifth


def test_build_name_audio_text_uses_gender_specific_templates(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    assert build_name_audio_text("Kevin", config, gender="male") == "Señor Kevin,"
    assert build_name_audio_text("María", config, gender="female") == "Señora María,"
    assert build_name_audio_text("Carlos", config, gender="unknown") == "Carlos,"


def test_normalize_name_audio_gender_supports_spanish_aliases() -> None:
    assert normalize_name_audio_gender("masculino") == "male"
    assert normalize_name_audio_gender("Señora") == "female"
    assert normalize_name_audio_gender("desconocido") == "unknown"


def test_get_cached_name_audio_returns_existing_file(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["name_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    rendered_text = build_name_audio_text("Juan Pérez", config, gender="unknown")
    cache_key = build_name_cache_key(
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="unknown",
        final_text=rendered_text,
    )
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
    mirror_dir = Path(str(config["name_audio"]["mirror_dirs"][0]))
    rendered_text = build_name_audio_text("Juan Pérez", config, gender="unknown")
    cache_key = build_name_cache_key(
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="unknown",
        final_text=rendered_text,
    )
    output_path = cache_dir / f"{cache_key}.wav"
    output_path.write_bytes(b"wav")

    def fail_generate(name: str, config_data: dict[str, object], gender: str | None = None) -> Path:
        raise AssertionError("generate_name_audio no debe llamarse si ya existe cache")

    monkeypatch.setattr(name_audio_cache, "generate_name_audio", fail_generate)

    cached_path = get_or_generate_name_audio("Juan Pérez", config)

    assert cached_path == output_path
    assert (mirror_dir / f"{cache_key}.wav").read_bytes() == b"wav"


def test_get_or_generate_name_audio_repairs_missing_mirror_on_cache_hit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["name_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    mirror_dir = Path(str(config["name_audio"]["mirror_dirs"][0]))
    rendered_text = build_name_audio_text("Juan Pérez", config, gender="unknown")
    cache_key = build_name_cache_key(
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="unknown",
        final_text=rendered_text,
    )
    output_path = cache_dir / f"{cache_key}.wav"
    output_path.write_bytes(b"wav")

    def fail_generate(name: str, config_data: dict[str, object], gender: str | None = None) -> Path:
        raise AssertionError("generate_name_audio no debe llamarse si ya existe cache")

    monkeypatch.setattr(name_audio_cache, "generate_name_audio", fail_generate)

    cached_path = get_or_generate_name_audio("Juan Pérez", config)

    assert cached_path == output_path
    assert (mirror_dir / f"{cache_key}.wav").read_bytes() == b"wav"


def test_get_or_generate_name_audio_makes_cached_audio_readable(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["name_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    mirror_dir = Path(str(config["name_audio"]["mirror_dirs"][0]))
    rendered_text = build_name_audio_text("Juan Pérez", config, gender="unknown")
    cache_key = build_name_cache_key(
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        gender="unknown",
        final_text=rendered_text,
    )
    output_path = cache_dir / f"{cache_key}.wav"
    output_path.write_bytes(b"wav")
    output_path.chmod(0o600)

    cached_path = get_or_generate_name_audio("Juan Pérez", config)

    assert cached_path == output_path
    assert oct(output_path.stat().st_mode & 0o777) == "0o644"
    assert oct((mirror_dir / f"{cache_key}.wav").stat().st_mode & 0o777) == "0o644"


def test_get_or_generate_name_audio_returns_none_when_api_key_is_missing(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    generated_path = get_or_generate_name_audio("Juan Pérez", config)

    assert generated_path is None
