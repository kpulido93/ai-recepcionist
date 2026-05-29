from __future__ import annotations

from pathlib import Path

from vicidial_vosk_cobranza_ivr.optima_9913_lab_audio import (
    OPTIMA_9913_DEUDA_BANCO,
    OPTIMA_9913_PREGUNTA_ABOGADO,
    OPTIMA_9913_SALUDO,
    build_optima_9913_lab_playback_path,
    build_optima_9913_lab_stem,
    build_optima_9913_lab_text,
    resolve_target_dirs,
)


def test_build_optima_9913_lab_text_uses_juridica_optima_and_abogado() -> None:
    saludo = build_optima_9913_lab_text(
        OPTIMA_9913_SALUDO,
        person_name="Maiquer",
        bank_name="Banco Caribe",
    )
    pregunta = build_optima_9913_lab_text(
        OPTIMA_9913_PREGUNTA_ABOGADO,
        person_name="Maiquer",
        bank_name="Banco Caribe",
    )
    deuda = build_optima_9913_lab_text(
        OPTIMA_9913_DEUDA_BANCO,
        person_name="Maiquer",
        bank_name="Banco Caribe",
    )

    assert saludo == "Saludos. ¿Hablo con Maiquer? Le escucho."
    assert "Jurídica Optima" in pregunta
    assert "abogado" in pregunta
    assert "asesor" not in pregunta
    assert "Banco Caribe" in deuda
    assert "abogado" in deuda


def test_build_optima_9913_lab_paths_use_expected_stems() -> None:
    assert build_optima_9913_lab_stem("lab-maiquer-caribe", OPTIMA_9913_SALUDO) == (
        "optima-lab-maiquer-caribe-saludo"
    )
    assert build_optima_9913_lab_playback_path(
        "lab-kevin-santander",
        OPTIMA_9913_PREGUNTA_ABOGADO,
    ) == ("custom/optima-lab-kevin-santander-pregunta-abogado")


def test_resolve_target_dirs_includes_primary_and_real_mirrors(tmp_path: Path) -> None:
    target_dirs = resolve_target_dirs(tmp_path / "custom")

    assert target_dirs[0] == (tmp_path / "custom").resolve()
    assert Path("/usr/share/asterisk/sounds/en/custom").resolve() in target_dirs
    assert Path("/var/lib/asterisk/sounds/custom").resolve() in target_dirs
