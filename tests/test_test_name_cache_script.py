from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


def load_script_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "test_name_cache.py"
    spec = importlib.util.spec_from_file_location("test_name_cache_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, cache_dir: Path, *, include_name_audio: bool = True) -> None:
    base_config = """
prompts:
  personalized_greeting_enabled: true
"""

    if not include_name_audio:
        path.write_text(base_config.strip(), encoding="utf-8")
        return

    path.write_text(
        (
            base_config
            + f"""
name_audio:
  enabled: true
  provider: "elevenlabs"
  cache_enabled: true
  cache_dir: "{cache_dir}"
  mirror_dirs: []
  playback_prefix: "custom/generated/names"
  version: "v1"
  max_name_chars: 80
  fallback_on_error: true
  templates:
    male: "Señor {{name}},"
    female: "Señora {{name}},"
    unknown: "{{name}},"
  elevenlabs:
    api_key_env: "ELEVENLABS_API_KEY"
    voice_id: "voice-demo"
    model_id: "model-demo"
    output_format: "wav"
    timeout_seconds: 15
"""
        ).strip(),
        encoding="utf-8",
    )


def test_inspect_name_audio_reports_disabled_when_name_audio_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "names", include_name_audio=False)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()

    report = module.inspect_name_audio("Kevin", module.load_config())

    assert report.status == "disabled"
    assert report.reason == "name_audio_disabled"
    assert report.generated is False
    assert report.cache_hit is False


def test_inspect_name_audio_reports_missing_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "names")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    module = load_script_module()

    report = module.inspect_name_audio("Kevin", module.load_config())

    assert report.status == "missing_api_key"
    assert report.reason == "missing_api_key"
    assert "ELEVENLABS_API_KEY" in report.message


def test_inspect_name_audio_reports_cache_hit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "names"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    module = load_script_module()
    generated_text = module.build_name_audio_text("Kevin", module.load_config(), gender="male")
    cache_key = module.build_name_cache_key(
        "Kevin",
        "voice-demo",
        "model-demo",
        "v1",
        gender="male",
        final_text=generated_text,
    )
    cached_path = cache_dir / f"{cache_key}.wav"
    cached_path.write_bytes(b"wav")
    cached_path.chmod(0o600)

    report = module.inspect_name_audio("Kevin", module.load_config(), gender="male")

    assert report.status == "cache_hit"
    assert report.reason == "cache_hit"
    assert report.generated is False
    assert report.cache_hit is True
    assert report.generated_text == "Señor Kevin,"
    assert report.playback_path == f"custom/generated/names/{cache_key}"
    assert report.wav_path == str(cached_path)
    assert oct(cached_path.stat().st_mode & 0o777) == "0o644"


def test_inspect_name_audio_reports_generated(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "names"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    module = load_script_module()
    generated_text = module.build_name_audio_text("Kevin", module.load_config(), gender="male")
    cache_key = module.build_name_cache_key(
        "Kevin",
        "voice-demo",
        "model-demo",
        "v1",
        gender="male",
        final_text=generated_text,
    )
    generated_path = cache_dir / f"{cache_key}.wav"
    generated_path.write_bytes(b"wav")

    monkeypatch.setattr(module, "get_cached_name_audio", lambda name, config, gender=None: None)
    monkeypatch.setattr(
        module,
        "get_or_generate_name_audio",
        lambda name, config, gender=None: generated_path,
    )

    report = module.inspect_name_audio("Kevin", module.load_config(), gender="male")

    assert report.status == "generated"
    assert report.reason == "generated"
    assert report.generated is True
    assert report.cache_hit is False
    assert report.generated_text == "Señor Kevin,"
    assert report.wav_path == str(generated_path)


def test_inspect_name_audio_reports_missing_name(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "names")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()

    report = module.inspect_name_audio("   ", module.load_config())

    assert report.status == "invalid_name"
    assert report.reason == "missing_name"
