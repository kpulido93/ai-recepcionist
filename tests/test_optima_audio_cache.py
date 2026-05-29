from __future__ import annotations

import wave
from pathlib import Path

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr import optima_audio_cache
from vicidial_vosk_cobranza_ivr.optima_audio_cache import (
    OPTIMA_DEUDA_BANCO,
    OPTIMA_SALUDO_NOMBRE,
    build_optima_audio_filename,
    build_optima_audio_text,
    build_optima_cache_key,
    get_cached_optima_audio,
    get_or_generate_optima_audio,
    normalize_optima_value,
)


def build_config(tmp_path: Path) -> dict[str, object]:
    return {
        "optima_audio": {
            "enabled": True,
            "provider": "elevenlabs",
            "cache_enabled": True,
            "cache_dir": str(tmp_path / "generated" / "optima"),
            "mirror_dirs": [str(tmp_path / "mirror" / "generated" / "optima")],
            "playback_prefix": "custom/generated/optima",
            "version": "v1-optima-segmented",
            "max_name_chars": 80,
            "max_bank_chars": 120,
            "fallback_on_error": True,
            "templates": {
                "saludo_nombre": "Saludos {name}.",
                "deuda_banco": "Por la deuda que mantiene en {bank}.",
            },
            "fallbacks": {
                "saludo_generico_audio": "custom/optima-01-saludo-generico",
                "deuda_generica_audio": "custom/optima-04-deuda-generica",
            },
        },
        "name_audio": {
            "elevenlabs": {
                "api_key_env": "ELEVENLABS_API_KEY",
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "output_format": "wav",
                "timeout_seconds": 15,
            }
        },
    }


def test_normalize_optima_value_removes_dangerous_chars() -> None:
    assert (
        normalize_optima_value('  Banco "Popular"; ../../  ', prompt_type=OPTIMA_DEUDA_BANCO)
        == "Banco Popular .. .."
    )


def test_build_optima_cache_key_is_deterministic_per_prompt_type() -> None:
    same_name_first = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        final_text="Saludos Juan Pérez.",
    )
    same_name_second = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        final_text="Saludos Juan Pérez.",
    )
    different_name = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Ana Pérez",
        "voice-demo",
        "model-demo",
        "v1",
        final_text="Saludos Ana Pérez.",
    )
    different_bank = build_optima_cache_key(
        OPTIMA_DEUDA_BANCO,
        "Banco Popular",
        "voice-demo",
        "model-demo",
        "v1",
        final_text="Por la deuda que mantiene en Banco Popular.",
    )

    assert same_name_first == same_name_second
    assert same_name_first != different_name
    assert same_name_first != different_bank


def test_get_cached_optima_audio_returns_existing_name_audio(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["optima_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    rendered_text = build_optima_audio_text(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)
    cache_key = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=rendered_text,
    )
    output_path = cache_dir / build_optima_audio_filename(OPTIMA_SALUDO_NOMBRE, cache_key)
    output_path.write_bytes(b"wav")

    cached_path = get_cached_optima_audio(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)

    assert cached_path == output_path


def test_get_cached_optima_audio_returns_existing_bank_audio(tmp_path: Path) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["optima_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    rendered_text = build_optima_audio_text(OPTIMA_DEUDA_BANCO, "Banco Popular", config)
    cache_key = build_optima_cache_key(
        OPTIMA_DEUDA_BANCO,
        "Banco Popular",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=rendered_text,
    )
    output_path = cache_dir / build_optima_audio_filename(OPTIMA_DEUDA_BANCO, cache_key)
    output_path.write_bytes(b"wav")

    cached_path = get_cached_optima_audio(OPTIMA_DEUDA_BANCO, "Banco Popular", config)

    assert cached_path == output_path


def test_get_or_generate_optima_audio_uses_cache_without_regeneration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["optima_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    mirror_dir = Path(str(config["optima_audio"]["mirror_dirs"][0]))
    rendered_text = build_optima_audio_text(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)
    cache_key = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        "Juan Pérez",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=rendered_text,
    )
    output_path = cache_dir / build_optima_audio_filename(OPTIMA_SALUDO_NOMBRE, cache_key)
    output_path.write_bytes(b"wav")

    def fail_generate(
        prompt_type: str,
        value: str,
        config_data: dict[str, object],
        *,
        force: bool = False,
    ) -> Path:
        del prompt_type, value, config_data, force
        raise AssertionError("generate_optima_audio no debe llamarse si ya existe cache")

    monkeypatch.setattr(optima_audio_cache, "generate_optima_audio", fail_generate)

    cached_path = get_or_generate_optima_audio(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)

    assert cached_path == output_path
    assert (mirror_dir / output_path.name).read_bytes() == b"wav"


def test_get_or_generate_optima_audio_force_regenerates(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["optima_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    rendered_text = build_optima_audio_text(OPTIMA_DEUDA_BANCO, "Banco Popular", config)
    cache_key = build_optima_cache_key(
        OPTIMA_DEUDA_BANCO,
        "Banco Popular",
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=rendered_text,
    )
    cached_path = cache_dir / build_optima_audio_filename(OPTIMA_DEUDA_BANCO, cache_key)
    cached_path.write_bytes(b"old")
    regenerated_path = cache_dir / "force-regenerated.wav"
    regenerated_path.write_bytes(b"new")

    observed_force_values: list[bool] = []

    def fake_generate(
        prompt_type: str,
        value: str,
        config_data: dict[str, object],
        *,
        force: bool = False,
    ) -> Path:
        del prompt_type, value, config_data
        observed_force_values.append(force)
        return regenerated_path

    monkeypatch.setattr(optima_audio_cache, "generate_optima_audio", fake_generate)

    resolved_path = get_or_generate_optima_audio(
        OPTIMA_DEUDA_BANCO,
        "Banco Popular",
        config,
        force=True,
    )

    assert resolved_path == regenerated_path
    assert observed_force_values == [True]


def test_get_or_generate_optima_audio_returns_none_when_api_key_is_missing(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    generated_path = get_or_generate_optima_audio(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)

    assert generated_path is None


def test_get_or_generate_optima_audio_loads_credentials_from_env_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    env_file = tmp_path / "elevenlabs.env"
    env_file.write_text(
        """
export ELEVENLABS_API_KEY=test-key
ELEVENLABS_VOICE_ID=voice-from-file
""".strip(),
        encoding="utf-8",
    )
    config["optima_audio"]["env_file"] = str(env_file)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)

    source_wav = tmp_path / "source.wav"
    with wave.open(str(source_wav), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x01\x00" * 400)

    observed_api_keys: list[str] = []

    def fake_request(text: str, config_data: dict[str, object], api_key: str) -> bytes:
        del text, config_data
        observed_api_keys.append(api_key)
        return source_wav.read_bytes()

    def fake_convert(source_path: Path, output_path: Path) -> None:
        del source_path
        output_path.write_bytes(source_wav.read_bytes())

    monkeypatch.setattr(optima_audio_cache, "_request_elevenlabs_audio", fake_request)
    monkeypatch.setattr(optima_audio_cache, "_convert_audio_to_wav", fake_convert)

    generated_path = get_or_generate_optima_audio(OPTIMA_SALUDO_NOMBRE, "Juan Pérez", config)

    assert generated_path is not None
    assert generated_path.exists()
    assert observed_api_keys == ["test-key"]
