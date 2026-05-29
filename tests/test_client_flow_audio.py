from __future__ import annotations

import json
import wave
from pathlib import Path

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr import client_flow_audio
from vicidial_vosk_cobranza_ivr.client_flow_audio import (
    build_client_flow_playback_path,
    build_client_flow_prompts,
    get_cached_client_flow_audio,
    get_or_generate_client_flow_audio,
)


def build_config(tmp_path: Path) -> dict[str, object]:
    return {
        "client_flow_audio": {
            "enabled": True,
            "provider": "elevenlabs",
            "cache_enabled": True,
            "cache_dir": str(tmp_path / "client-flow"),
            "mirror_dirs": [str(tmp_path / "mirror")],
            "playback_prefix": "custom/generated/client-flow-9912",
            "version": "v2-client-flow-9912",
            "fallback_on_error": True,
            "defaults": {
                "debtor": "Kevin",
                "bank": "Banco de Prueba",
                "gender": "male",
            },
            "prompts": {
                "greeting_templates": {
                    "male": "Saludos. ¿Cómo está, señor {name}?",
                    "female": "Saludos. ¿Cómo está, señora {name}?",
                    "unknown": "Saludos. ¿Cómo está, {name}?",
                },
                "bank": "Le llamo con relación a la deuda que usted mantiene con el {bank}.",
                "debt_known": (
                    "Le estamos llamando por la deuda que tiene con {bank}, que usted ya conoce."
                ),
            },
            "trailing_silence_ms": 800,
            "elevenlabs": {
                "api_key_env": "ELEVENLABS_API_KEY",
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "output_format": "wav",
                "timeout_seconds": 15,
            },
        }
    }


def test_build_client_flow_prompts_uses_defaults(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    greeting_prompt, bank_prompt, debt_known_prompt = build_client_flow_prompts(config)

    assert greeting_prompt.text == "Saludos. ¿Cómo está, señor Kevin?"
    assert bank_prompt.text == (
        "Le llamo con relación a la deuda que usted mantiene con el Banco de Prueba."
    )
    assert debt_known_prompt.text == (
        "Le estamos llamando por la deuda que tiene con Banco de Prueba, que usted ya conoce."
    )
    assert greeting_prompt.playback_path == build_client_flow_playback_path("greeting", config)
    assert bank_prompt.playback_path == build_client_flow_playback_path("bank", config)
    assert debt_known_prompt.playback_path == build_client_flow_playback_path(
        "deuda-conocida", config
    )


def test_build_client_flow_prompts_supports_gendered_greetings(tmp_path: Path) -> None:
    config = build_config(tmp_path)

    male_prompt, _, _ = build_client_flow_prompts(config, debtor="Kevin", gender="male")
    female_prompt, _, _ = build_client_flow_prompts(config, debtor="Ana", gender="female")
    unknown_prompt, _, _ = build_client_flow_prompts(config, debtor="Alex", gender="unknown")

    assert male_prompt.text == "Saludos. ¿Cómo está, señor Kevin?"
    assert female_prompt.text == "Saludos. ¿Cómo está, señora Ana?"
    assert unknown_prompt.text == "Saludos. ¿Cómo está, Alex?"


def test_get_cached_client_flow_audio_returns_existing_file_when_metadata_matches(
    tmp_path: Path,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["client_flow_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    greeting_prompt, _, _ = build_client_flow_prompts(config)
    cached_path = cache_dir / "greeting.wav"
    cached_path.write_bytes(b"wav")
    (cache_dir / "greeting.json").write_text(
        json.dumps(
            {
                "text": greeting_prompt.text,
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "version": "v2-client-flow-9912",
            }
        ),
        encoding="utf-8",
    )

    cached_audio = get_cached_client_flow_audio("greeting", greeting_prompt.text, config)

    assert cached_audio == cached_path


def test_get_or_generate_client_flow_audio_uses_cache_and_repairs_mirror(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["client_flow_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    mirror_dir = Path(str(config["client_flow_audio"]["mirror_dirs"][0]))
    greeting_prompt, _, _ = build_client_flow_prompts(config)
    cached_path = cache_dir / "greeting.wav"
    cached_path.write_bytes(b"wav")
    cached_path.chmod(0o600)
    (cache_dir / "greeting.json").write_text(
        json.dumps(
            {
                "text": greeting_prompt.text,
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "version": "v2-client-flow-9912",
            }
        ),
        encoding="utf-8",
    )

    def fail_generate(slot: str, text: str, config_data: dict[str, object]) -> Path:
        raise AssertionError("generate_client_flow_audio no debe llamarse si ya existe cache")

    monkeypatch.setattr(client_flow_audio, "generate_client_flow_audio", fail_generate)

    cached_audio = get_or_generate_client_flow_audio("greeting", greeting_prompt.text, config)

    assert cached_audio == cached_path
    assert (mirror_dir / "greeting.wav").read_bytes() == b"wav"
    assert oct(cached_path.stat().st_mode & 0o777) == "0o644"


def test_get_or_generate_client_flow_audio_returns_none_when_api_key_is_missing(
    tmp_path: Path,
) -> None:
    config = build_config(tmp_path)
    greeting_prompt, _, _ = build_client_flow_prompts(config)

    generated_path = get_or_generate_client_flow_audio("greeting", greeting_prompt.text, config)

    assert generated_path is None


def test_get_cached_client_flow_audio_invalidates_when_greeting_text_changes(
    tmp_path: Path,
) -> None:
    config = build_config(tmp_path)
    cache_dir = Path(str(config["client_flow_audio"]["cache_dir"]))
    cache_dir.mkdir(parents=True)
    cached_path = cache_dir / "greeting.wav"
    cached_path.write_bytes(b"wav")
    (cache_dir / "greeting.json").write_text(
        json.dumps(
            {
                "text": "Saludos. ¿Cómo está, Kevin?",
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "version": "v2-client-flow-9912",
            }
        ),
        encoding="utf-8",
    )
    greeting_prompt, _, _ = build_client_flow_prompts(config)

    cached_audio = get_cached_client_flow_audio("greeting", greeting_prompt.text, config)

    assert cached_audio is None


def test_generate_client_flow_audio_appends_trailing_silence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config = build_config(tmp_path)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    input_wav = tmp_path / "input.wav"
    with wave.open(str(input_wav), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(8000)
        wav_file.writeframes(b"\x01\x00" * 800)

    def fake_request(text: str, config_data: dict[str, object], api_key: str) -> bytes:
        del text, config_data, api_key
        return input_wav.read_bytes()

    def fake_convert(source_path: Path, output_path: Path) -> None:
        del source_path
        output_path.write_bytes(input_wav.read_bytes())

    monkeypatch.setattr(client_flow_audio, "_request_elevenlabs_audio", fake_request)
    monkeypatch.setattr(client_flow_audio, "_convert_audio_to_wav", fake_convert)

    generated_path = client_flow_audio.generate_client_flow_audio(
        "greeting",
        "Saludos. ¿Cómo está, señor Kevin?",
        config,
    )

    with wave.open(str(generated_path), "rb") as generated_wav:
        assert generated_wav.getframerate() == 8000
        assert generated_wav.getnchannels() == 1
        assert generated_wav.getsampwidth() == 2
        assert generated_wav.getnframes() == 7200
