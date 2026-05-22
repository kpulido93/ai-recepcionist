from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from vicidial_vosk_cobranza_ivr.config import (
    AppConfig,
    AsteriskSettings,
    AudioSettings,
    IvrSettings,
    LoggingSettings,
    PromptsSettings,
    VoskSettings,
)
from vicidial_vosk_cobranza_ivr.routing import load_routing_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "agi" / "resolve_transfer_target.py"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_SPEC = importlib.util.spec_from_file_location("agi_resolve_transfer_target", SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
resolve_transfer_target_agi = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = resolve_transfer_target_agi
_SPEC.loader.exec_module(resolve_transfer_target_agi)


class FakeSession:
    def __init__(self, *, get_variable_values: dict[str, str] | None = None) -> None:
        self.variables: dict[str, str] = {}
        self.get_variable_values = get_variable_values or {}

    def set_variable(self, name: str, value: str) -> str:
        self.variables[name] = value
        return "200 result=1"

    def get_variable(self, name: str) -> str | None:
        return self.get_variable_values.get(name)


def build_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        audio=AudioSettings(min_rms=150.0),
        ivr=IvrSettings(
            listen_seconds=5,
            sample_rate=8000,
            retry_attempts=1,
            default_intent="DUDA",
            allow_dtmf_fallback=True,
            early_detection_enabled=True,
            early_detection_min_audio_ms=250,
            early_detection_min_chars=2,
            vad_enabled=True,
            min_speech_ms=250,
            silence_after_speech_ms=700,
            rms_speech_threshold=250.0,
            max_dtmf_wait_ms=5000,
            dtmf_map={"1": "SI", "2": "NO"},
        ),
        asterisk=AsteriskSettings(
            app_name="vicidial-vosk-cobranza-ivr",
            channel_variable_name="VOSK_INTENT",
            transfer_context="default",
            lawyer_destination_type="ingroup",
            lawyer_destination="INGROUP_ABOGADOS",
            final_disposition_yes="YES",
            final_disposition_no="NO",
            final_disposition_unknown="UNKNOWN",
        ),
        vosk=VoskSettings(
            websocket_url="ws://127.0.0.1:2700",
            sample_rate=8000,
            audio_format="s16le",
            language="es",
            websocket_timeout_seconds=10,
        ),
        logging=LoggingSettings(
            enabled=False,
            log_level="INFO",
            log_path="./logs/test.log",
            events_path="",
            log_transcript=False,
            mask_phone_numbers=True,
            debug_audio_dump_enabled=False,
            debug_audio_dump_dir="/tmp",
            rotate_max_bytes=10485760,
            rotate_backup_count=10,
        ),
        prompts=PromptsSettings(
            personalized_greeting_enabled=True,
            greeting_template=(
                "Hola {client_name}, nos comunicamos de SokaCorp por una gestion pendiente "
                "relacionada con {bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_template_without_name=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente relacionada con "
                "{bank_name}. ¿Desea que le comuniquemos ahora? Le escucho."
            ),
            greeting_fallback=(
                "Hola, nos comunicamos de SokaCorp por una gestion pendiente. "
                "¿Desea que le comuniquemos ahora? Le escucho."
            ),
            generated_audio_dir=str(tmp_path / "generated"),
            generated_audio_playback_prefix="custom/generated",
            tts_provider="espeak-ng",
            tts_voice="es-la",
            cache_enabled=True,
            privacy_mode=False,
            debug_log_values=False,
        ),
        intents={"SI": ["si"], "NO": ["no"], "DUDA": ["quien habla"], "SILENCIO": []},
    )


def build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.NullHandler())
    return logger


def test_run_resolve_transfer_target_sets_variable_for_bank(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.yml"
    routing_path.write_text(
        """
default_transfer_target: "PJSIP/1002"
portfolios:
  banco_bhd:
    bank_names:
      - "Banco BHD"
      - "BHD"
    transfer_target: "PJSIP/1003"
""".strip(),
        encoding="utf-8",
    )
    routing_config = load_routing_config(routing_path)
    config = build_config(tmp_path)
    session = FakeSession(get_variable_values={"IVR_BANK_NAME": "Banco BHD"})
    logger = build_logger("test_resolve_transfer_target_agi.bank")

    result = resolve_transfer_target_agi.run_resolve_transfer_target(
        session=session,
        config=config,
        logger=logger,
        environment={},
        routing_config=routing_config,
    )

    assert result == 0
    assert session.variables["IVR_TRANSFER_TARGET"] == "PJSIP/1003"
