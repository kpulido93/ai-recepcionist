from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch

from vicidial_vosk_cobranza_ivr.optima_audio_cache import (
    OPTIMA_DEUDA_BANCO,
    OPTIMA_SALUDO_NOMBRE,
    build_optima_audio_filename,
    build_optima_audio_text,
    build_optima_cache_key,
)


def load_script_module() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "generate_elevenlabs_optima_prompts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_elevenlabs_optima_prompts_script",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_config(path: Path, cache_dir: Path, csv_path: Path) -> None:
    path.write_text(
        f"""
lead_context:
  csv_path: "{csv_path}"
name_audio:
  elevenlabs:
    api_key_env: "ELEVENLABS_API_KEY"
    voice_id: "voice-demo"
    model_id: "model-demo"
    output_format: "wav"
    timeout_seconds: 15
optima_audio:
  enabled: true
  provider: "elevenlabs"
  cache_enabled: true
  cache_dir: "{cache_dir}"
  mirror_dirs: []
  playback_prefix: "custom/generated/optima"
  version: "v1-optima-segmented"
  max_name_chars: 80
  max_bank_chars: 120
  fallback_on_error: true
  templates:
    saludo_nombre: "Saludos {{name}}."
    deuda_banco: "Por la deuda que mantiene en {{bank}}."
  fallbacks:
    saludo_generico_audio: "custom/optima-01-saludo-generico"
    deuda_generica_audio: "custom/optima-04-deuda-generica"
""".strip(),
        encoding="utf-8",
    )


def write_csv(path: Path) -> None:
    path.write_text(
        """lead_id,phone_number,client_name,client_gender,bank_name,portfolio_id,campaign_id,list_id
lab-1,1001,Juan,male,Banco Popular,popular,LAB,LIST
lab-2,1002,Ana,female,Banco Popular,popular,LAB,LIST
lab-3,1003,Juan,male,Banco Reservas,reservas,LAB,LIST
""",
        encoding="utf-8",
    )


def test_build_dynamic_prompts_from_csv_deduplicates_names_and_banks(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    write_csv(csv_path)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "generated" / "optima", csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()
    config = module.load_config()

    prompts = module.build_dynamic_prompts_from_csv(csv_path, config)

    assert len(prompts) == 4
    assert sum(prompt.prompt_type == OPTIMA_SALUDO_NOMBRE for prompt in prompts) == 2
    assert sum(prompt.prompt_type == OPTIMA_DEUDA_BANCO for prompt in prompts) == 2


def test_ensure_dynamic_prompts_skips_existing_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    write_csv(csv_path)
    cache_dir = tmp_path / "generated" / "optima"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()
    config = module.load_config()
    prompts = module.build_dynamic_prompts_from_csv(csv_path, config)

    saludo_prompt = next(prompt for prompt in prompts if prompt.prompt_type == OPTIMA_SALUDO_NOMBRE)
    saludo_key = build_optima_cache_key(
        OPTIMA_SALUDO_NOMBRE,
        saludo_prompt.value,
        "voice-demo",
        "model-demo",
        "v1-optima-segmented",
        final_text=build_optima_audio_text(OPTIMA_SALUDO_NOMBRE, saludo_prompt.value, config),
    )
    saludo_path = cache_dir / build_optima_audio_filename(OPTIMA_SALUDO_NOMBRE, saludo_key)
    saludo_path.write_bytes(b"wav")

    reports = module.ensure_dynamic_prompts(
        (saludo_prompt,),
        config,
        base_dir=cache_dir,
        mirror_dirs=(),
        force=False,
        dry_run=False,
    )

    assert reports[0].status == "skipped_existing"
    assert reports[0].wav_path == str(saludo_path)


def test_ensure_dynamic_prompts_force_passes_force_flag(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    write_csv(csv_path)
    cache_dir = tmp_path / "generated" / "optima"
    cache_dir.mkdir(parents=True)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, cache_dir, csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()
    config = module.load_config()
    prompt = module.build_dynamic_prompts_from_csv(csv_path, config)[0]
    generated_path = cache_dir / "forced.wav"
    generated_path.write_bytes(b"wav")

    observed_force_values: list[bool] = []

    def fake_get_or_generate(
        prompt_type: str,
        value: str,
        config_data: dict[str, object],
        *,
        force: bool = False,
    ) -> Path:
        del prompt_type, value, config_data
        observed_force_values.append(force)
        return generated_path

    monkeypatch.setattr(module, "get_or_generate_optima_audio", fake_get_or_generate)
    monkeypatch.setattr(
        module,
        "validate_wav_file",
        lambda path: module.ValidationReport("ok", "", str(path)),
    )

    reports = module.ensure_dynamic_prompts(
        (prompt,),
        config,
        base_dir=cache_dir,
        mirror_dirs=(),
        force=True,
        dry_run=False,
    )

    assert reports[0].status == "generated"
    assert observed_force_values == [True]


def test_main_dry_run_reports_generation_from_csv(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    write_csv(csv_path)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "generated" / "optima", csv_path)
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    module = load_script_module()

    exit_code = module.main(["--dest", str(tmp_path / "custom"), "--dry-run"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "static_generated=0" in output
    assert "dynamic_generated=0" in output
    assert "category=dynamic" in output
    assert str(csv_path) in output


def test_main_reports_env_file_load_without_exposing_values(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys,
) -> None:
    csv_path = tmp_path / "lead_context.sample.csv"
    write_csv(csv_path)
    config_path = tmp_path / "ivr.yml"
    write_config(config_path, tmp_path / "generated" / "optima", csv_path)
    env_file = tmp_path / "elevenlabs.env"
    env_file.write_text(
        """
export ELEVENLABS_API_KEY=test-key
ELEVENLABS_VOICE_ID=voice-demo
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("VOSK_COBRANZA_CONFIG", str(config_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    module = load_script_module()

    exit_code = module.main(
        ["--dest", str(tmp_path / "custom"), "--dry-run", "--env-file", str(env_file)]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Loaded ELEVENLABS_API_KEY from env-file: yes" in output
    assert "test-key" not in output
