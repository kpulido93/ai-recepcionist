from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


def load_script_module() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "generate_optima_elevenlabs_prompts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_optima_elevenlabs_prompts_script",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, csv_path: Path) -> None:
    path.write_text(
        f"""
lead_context:
  csv_path: "{csv_path}"
optima_audio:
  elevenlabs:
    voice_id_env: "ELEVENLABS_VOICE_ID"
    voice_id: "voice-from-config"
    model_id: "eleven_multilingual_v2"
    output_format: "mp3_44100_128"
    timeout_seconds: 15
""".strip(),
        encoding="utf-8",
    )


def write_csv(path: Path) -> None:
    path.write_text(
        """lead_id,phone_number,client_name,client_gender,bank_name,portfolio_id,campaign_id,list_id
lab-1003,1003,María,female,Banco BHD,bhd_mora_60,LAB-CAMP,LAB-LIST
""",
        encoding="utf-8",
    )


def test_resolve_prompt_context_uses_csv_defaults(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    config_path = tmp_path / "ivr.yml"
    write_csv(csv_path)
    write_config(config_path, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()
    config = module.load_config()

    context = module.resolve_prompt_context(
        config,
        lead_id="lab-1003",
        client_name="",
        bank_name="",
    )

    assert context.lead_id == "lab-1003"
    assert context.client_name == "María"
    assert context.bank_name == "Banco BHD"


def test_build_prepared_prompts_skips_dynamic_entries_without_context() -> None:
    module = load_script_module()
    context = module.LeadPromptContext(lead_id=None, client_name=None, bank_name=None)

    prompts = module.build_prepared_prompts(context, Path("/tmp/custom"))

    assert [prompt.filename_stem for prompt in prompts] == [
        "optima-04-permitame-terminar",
        "optima-05-no-entendi",
    ]


def test_resolve_provider_settings_prefers_environment_voice_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    config_path = tmp_path / "ivr.yml"
    write_csv(csv_path)
    write_config(config_path, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice-from-env")
    module = load_script_module()
    config = module.load_config()

    settings = module.resolve_provider_settings(config)

    assert settings.voice_id == "voice-from-env"
    assert settings.voice_source == "environment"
    assert settings.model_id == "eleven_multilingual_v2"


def test_main_dry_run_reports_expected_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    config_path = tmp_path / "ivr.yml"
    write_csv(csv_path)
    write_config(config_path, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    module = load_script_module()

    exit_code = module.main(["--dry-run", "--install-dir", str(tmp_path / "custom")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "ELEVENLABS_API_KEY available: no" in output
    assert "dry_run filename=optima-01-saludo-validacion.wav" in output
    assert "dry_run filename=optima-05-no-entendi.wav" in output


def test_main_without_api_key_skips_real_generation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    config_path = tmp_path / "ivr.yml"
    write_csv(csv_path)
    write_config(config_path, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    module = load_script_module()

    exit_code = module.main(["--install-dir", str(tmp_path / "custom")])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "generation_skipped: ELEVENLABS_API_KEY not available" in output
    assert not (tmp_path / "custom").exists()
