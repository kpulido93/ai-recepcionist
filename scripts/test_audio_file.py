#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
import wave
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prueba local de WAV contra la misma logica del AGI. "
            "El script no remuestrea: usa el sample rate real del WAV salvo override explicito."
        )
    )
    parser.add_argument("wav_file", type=Path, help="Archivo WAV mono PCM 16-bit")
    parser.add_argument(
        "--dtmf",
        default=None,
        help="Digito DTMF opcional para forzar clasificacion",
    )
    parser.add_argument("--config", type=Path, default=None, help="Ruta alternativa a ivr.yml")
    parser.add_argument("--intents", type=Path, default=None, help="Ruta alternativa a intents.yml")
    parser.add_argument("--vosk-url", default=None, help="Override del WebSocket de Vosk")
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=None,
        help="Override del sample rate informado a Vosk. No remuestrea el audio.",
    )
    parser.add_argument(
        "--show-partials",
        action="store_true",
        help="Muestra partials devueltos por Vosk si existen",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from agi.vosk_cobranza import send_audio_to_vosk as agi_send_audio_to_vosk
    from vicidial_vosk_cobranza_ivr.app import build_service
    from vicidial_vosk_cobranza_ivr.audio import AudioFormatError, read_wave_file
    from vicidial_vosk_cobranza_ivr.config import (
        ConfigError,
        load_app_config,
        resolve_runtime_paths,
    )
    from vicidial_vosk_cobranza_ivr.intent_classifier import intent_value

    args = parse_args(argv)

    try:
        runtime_paths = resolve_runtime_paths(
            config_path=args.config,
            intents_path=args.intents,
        )
        config = load_app_config(runtime_paths.config_path, runtime_paths.intents_path)
        audio_packet = read_wave_file(args.wav_file)
    except (AudioFormatError, ConfigError, FileNotFoundError, wave.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    effective_sample_rate = args.sample_rate or audio_packet.sample_rate
    if args.sample_rate is not None and args.sample_rate != audio_packet.sample_rate:
        print(
            (
                "WARN: --sample-rate sobreescribe el header WAV y no remuestrea el audio. "
                "wav_sample_rate="
                f"{audio_packet.sample_rate} effective_sample_rate={effective_sample_rate}"
            ),
            file=sys.stderr,
        )
    elif effective_sample_rate != 8000:
        print(
            (
                "WARN: el AGI normalmente trabaja con 8000 Hz. "
                f"Este script enviara el WAV tal como viene: sample_rate={effective_sample_rate}"
            ),
            file=sys.stderr,
        )

    websocket_url = args.vosk_url or config.vosk.websocket_url
    runtime_config = replace(
        config,
        vosk=replace(config.vosk, websocket_url=websocket_url),
    )

    logger = logging.getLogger("vicidial_vosk_cobranza_ivr.scripts.test_audio_file")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False

    service = build_service(
        config=runtime_config,
        logger=logger,
        audio_sender=agi_send_audio_to_vosk,
    )
    outcome = service.classify_audio_bytes(
        audio_bytes=audio_packet.audio_bytes,
        sample_rate=effective_sample_rate,
        dtmf=args.dtmf,
    )
    partials = _extract_partials(outcome.raw_messages)

    print(f"file: {args.wav_file}")
    print(f"sample_rate: {effective_sample_rate}")
    print(f"text: {outcome.transcript}")
    print(f"intent: {intent_value(outcome.intent)}")
    print(f"confidence: {outcome.confidence:.2f}")
    print(f"source: {outcome.source}")
    if args.show_partials:
        print(f"partials: {json.dumps(partials, ensure_ascii=False)}")

    return 1 if outcome.source == "error" else 0


def _extract_partials(raw_messages: Sequence[dict[str, object]]) -> list[str]:
    partials: list[str] = []
    for message in raw_messages:
        partial = str(message.get("partial", "")).strip()
        if partial:
            partials.append(partial)
    return partials


if __name__ == "__main__":
    raise SystemExit(main())
