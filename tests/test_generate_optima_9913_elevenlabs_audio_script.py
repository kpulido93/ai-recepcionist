from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from pytest import MonkeyPatch


def load_script_module() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "generate_optima_9913_elevenlabs_audio.py"
    )
    spec = importlib.util.spec_from_file_location(
        "generate_optima_9913_elevenlabs_audio_script",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_env_file_supports_export_and_quotes(tmp_path: Path) -> None:
    module = load_script_module()
    env_file = tmp_path / "vicidial-vosk.env"
    env_file.write_text(
        """
# comentario
export ELEVENLABS_API_KEY="secret"
ELEVENLABS_VOICE_ID='voice-id'
IGNORED=value
""".strip(),
        encoding="utf-8",
    )

    parsed = module.parse_env_file(env_file)

    assert parsed["ELEVENLABS_API_KEY"] == "secret"
    assert parsed["ELEVENLABS_VOICE_ID"] == "voice-id"
    assert parsed["IGNORED"] == "value"


def test_load_env_file_if_needed_reads_default_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = load_script_module()
    env_file = tmp_path / "vicidial-vosk.env"
    env_file.write_text(
        "ELEVENLABS_API_KEY=test-key\nELEVENLABS_VOICE_ID=test-voice\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)

    loaded = module.load_env_file_if_needed(env_file)

    assert loaded is True
    assert module.os.getenv("ELEVENLABS_API_KEY") == "test-key"
    assert module.os.getenv("ELEVENLABS_VOICE_ID") == "test-voice"


def test_prompt_specs_use_neutral_static_base_texts() -> None:
    module = load_script_module()

    prompts = {prompt.filename: prompt.text for prompt in module.PROMPT_SPECS}
    silences = {prompt.filename: prompt.leading_silence_ms for prompt in module.PROMPT_SPECS}

    assert prompts["optima-01-saludo-validacion.wav"] == "Saludos. ¿Hablo con usted? Le escucho."
    assert "Jurídica Optima" in prompts["optima-02-pregunta-abogado.wav"]
    assert "abogado" in prompts["optima-02-pregunta-abogado.wav"]
    assert "asesor" not in prompts["optima-02-pregunta-abogado.wav"]
    assert "deuda que usted ya conoce" in prompts["optima-03-deuda-banco.wav"]
    assert silences["optima-01-saludo-validacion.wav"] == 500
    assert silences["optima-02-pregunta-abogado.wav"] == 250
    assert silences["optima-03-deuda-banco.wav"] == 250
    assert silences["optima-05-no-entendi.wav"] == 250


def test_resolve_target_dirs_adds_real_asterisk_mirrors(tmp_path: Path) -> None:
    module = load_script_module()

    target_dirs = module.resolve_target_dirs(tmp_path / "custom", [])
    en_custom_dir = Path("/usr/share/asterisk/sounds/en/custom").resolve()
    var_lib_dir = Path("/var/lib/asterisk/sounds/custom").resolve()

    assert target_dirs[0] == (tmp_path / "custom").resolve()
    assert en_custom_dir in target_dirs
    assert var_lib_dir in target_dirs


def test_all_outputs_exist_requires_wav_and_slin(tmp_path: Path) -> None:
    module = load_script_module()
    install_dir = tmp_path / "custom"
    install_dir.mkdir(parents=True)
    wav_path = install_dir / "optima-01-saludo-validacion.wav"
    slin_path = install_dir / "optima-01-saludo-validacion.slin"

    wav_path.write_bytes(b"wav")
    assert module.all_outputs_exist((install_dir,), "optima-01-saludo-validacion.wav") is False

    slin_path.write_bytes(b"slin")
    assert module.all_outputs_exist((install_dir,), "optima-01-saludo-validacion.wav") is True


def test_main_dry_run_reports_expected_files(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys,
) -> None:
    module = load_script_module()
    env_file = tmp_path / "vicidial-vosk.env"
    env_file.write_text(
        "ELEVENLABS_API_KEY=test-key\nELEVENLABS_VOICE_ID=test-voice\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)

    exit_code = module.main(
        [
            "--dry-run",
            "--env-file",
            str(env_file),
            "--install-dir",
            str(tmp_path / "custom"),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "ELEVENLABS_API_KEY loaded: True" in output
    assert "Loaded ELEVENLABS_API_KEY from env-file: yes" in output
    assert "dry_run filename=optima-01-saludo-validacion.wav" in output
    assert "dry_run filename=optima-05-no-entendi.wav" in output
    assert "stem=optima-lab-maiquer-caribe-saludo" in output
    assert "stem=optima-lab-kevin-santander-pregunta-abogado" in output
    assert str(Path("/usr/share/asterisk/sounds/en/custom").resolve()) in output
