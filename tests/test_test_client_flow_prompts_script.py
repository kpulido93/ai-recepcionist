from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


def load_script_module() -> ModuleType:
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "test_client_flow_prompts.py"
    spec = importlib.util.spec_from_file_location("test_client_flow_prompts_script", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, cache_dir: Path) -> None:
    path.write_text(
        f"""
client_flow_audio:
  enabled: true
  provider: "elevenlabs"
  cache_enabled: true
  cache_dir: "{cache_dir}"
  mirror_dirs: []
  playback_prefix: "custom/generated/client-flow-9912"
  version: "v2-client-flow-9912"
  fallback_on_error: true
  defaults:
    debtor: "Kevin"
    bank: "Banco de Prueba"
    gender: "male"
  prompts:
    greeting_templates:
      male: "Saludos. ¿Cómo está, señor {{name}}?"
      female: "Saludos. ¿Cómo está, señora {{name}}?"
      unknown: "Saludos. ¿Cómo está, {{name}}?"
    bank: "Le llamo con relación a la deuda que usted mantiene con el {{bank}}."
    debt_known: "Le estamos llamando por la deuda que tiene con {{bank}}, que usted ya conoce."
  elevenlabs:
    api_key_env: "ELEVENLABS_API_KEY"
    voice_id: "voice-demo"
    model_id: "model-demo"
    output_format: "wav"
    timeout_seconds: 15
""".strip(),
        encoding="utf-8",
    )


def test_inspect_prompt_reports_missing_api_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "client-flow")
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    module = load_script_module()
    prompt = module.build_client_flow_prompts(module.load_config())[0]

    report = module.inspect_prompt(prompt, module.load_config())

    assert report.status == "missing_api_key"
    assert report.reason == "missing_api_key"
    assert "ELEVENLABS_API_KEY" in report.message


def test_inspect_prompt_reports_cache_hit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "client-flow"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    module = load_script_module()
    prompt = module.build_client_flow_prompts(module.load_config())[0]
    cached_path = cache_dir / "greeting.wav"
    cached_path.write_bytes(b"wav")
    (cache_dir / "greeting.json").write_text(
        json.dumps(
            {
                "text": prompt.text,
                "voice_id": "voice-demo",
                "model_id": "model-demo",
                "version": "v2-client-flow-9912",
            }
        ),
        encoding="utf-8",
    )

    report = module.inspect_prompt(prompt, module.load_config())

    assert report.status == "cache_hit"
    assert report.reason == "cache_hit"
    assert report.cache_hit is True
    assert report.generated is False
    assert report.playback_path == "custom/generated/client-flow-9912/greeting"
    assert report.wav_path == str(cached_path)


def test_main_accepts_gender_override(tmp_path: Path, monkeypatch: MonkeyPatch, capsys) -> None:
    cache_dir = tmp_path / "client-flow"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    module = load_script_module()
    generated_path = cache_dir / "greeting.wav"
    generated_path.write_bytes(b"wav")
    monkeypatch.setattr(module, "get_cached_client_flow_audio", lambda slot, text, config: None)
    monkeypatch.setattr(
        module,
        "get_or_generate_client_flow_audio",
        lambda slot, text, config: generated_path,
    )

    exit_code = module.main(["--debtor", "Ana", "--gender", "female"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Saludos. ¿Cómo está, señora Ana?" in output


def test_inspect_prompt_reports_generated(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "client-flow"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    module = load_script_module()
    prompt = module.build_client_flow_prompts(module.load_config())[0]
    generated_path = cache_dir / "greeting.wav"
    generated_path.write_bytes(b"wav")

    monkeypatch.setattr(module, "get_cached_client_flow_audio", lambda slot, text, config: None)
    monkeypatch.setattr(
        module,
        "get_or_generate_client_flow_audio",
        lambda slot, text, config: generated_path,
    )

    report = module.inspect_prompt(prompt, module.load_config())

    assert report.status == "generated"
    assert report.reason == "generated"
    assert report.generated is True
    assert report.cache_hit is False
    assert report.wav_path == str(generated_path)
