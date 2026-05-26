from __future__ import annotations

import os
import select
import struct
import time
import wave
from dataclasses import dataclass
from math import sqrt
from pathlib import Path


class AudioFormatError(RuntimeError):
    """Raised when audio format is not compatible with the simple V1 pipeline."""


@dataclass(frozen=True)
class AudioPacket:
    audio_bytes: bytes
    sample_rate: int


@dataclass(frozen=True)
class CaptureResult:
    audio_bytes: bytes
    bytes_read: int
    duration_ms: int
    speech_started: bool
    finish_reason: str
    silence_ms: int = 0
    average_rms: float = 0.0
    max_rms: float = 0.0


def calculate_rms(audio_bytes: bytes) -> float:
    if len(audio_bytes) < 2:
        return 0.0

    frame_count = len(audio_bytes) // 2
    if frame_count == 0:
        return 0.0

    samples = struct.unpack(f"<{frame_count}h", audio_bytes[: frame_count * 2])
    square_sum = sum(sample * sample for sample in samples)
    return float(sqrt(square_sum / frame_count))


def read_wave_file(path: Path) -> AudioPacket:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        if channels != 1:
            raise AudioFormatError("El WAV debe ser mono.")
        if sample_width != 2:
            raise AudioFormatError("El WAV debe ser PCM 16-bit.")

        return AudioPacket(
            audio_bytes=wav_file.readframes(wav_file.getnframes()),
            sample_rate=sample_rate,
        )


def capture_eagi_audio(
    fd: int,
    listen_seconds: int,
    sample_rate: int,
    chunk_size: int = 3200,
) -> bytes:
    return capture_eagi_audio_result(
        fd=fd,
        listen_seconds=listen_seconds,
        sample_rate=sample_rate,
        chunk_size=chunk_size,
        vad_enabled=False,
    ).audio_bytes


def capture_eagi_audio_result(
    fd: int,
    listen_seconds: int,
    sample_rate: int,
    *,
    chunk_size: int = 3200,
    vad_enabled: bool = True,
    min_speech_ms: int = 250,
    silence_after_speech_ms: int = 700,
    rms_speech_threshold: float = 250.0,
    initial_silence_timeout_ms: int | None = None,
) -> CaptureResult:
    if os.name == "nt":
        raise RuntimeError("La captura EAGI solo se ejecuta en Linux.")

    bytes_per_second = sample_rate * 2
    target_bytes = bytes_per_second * listen_seconds
    deadline = time.monotonic() + listen_seconds + 0.5
    chunks: list[bytes] = []
    bytes_read = 0
    speech_started = False
    candidate_speech_bytes = 0
    speech_bytes = 0
    silence_after_speech_bytes = 0
    finish_reason = "timeout"
    rms_weighted_sum = 0.0
    max_rms = 0.0

    while bytes_read < target_bytes and time.monotonic() < deadline:
        timeout = max(0.0, min(0.2, deadline - time.monotonic()))
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            continue

        chunk = os.read(fd, min(chunk_size, target_bytes - bytes_read))
        if not chunk:
            finish_reason = "no_audio" if not speech_started else "timeout"
            break

        chunk_rms = calculate_rms(chunk)
        rms_weighted_sum += chunk_rms * len(chunk)
        max_rms = max(max_rms, chunk_rms)
        is_speech = chunk_rms >= rms_speech_threshold
        chunks.append(chunk)
        bytes_read += len(chunk)
        if is_speech:
            silence_after_speech_bytes = 0
            if not vad_enabled:
                speech_started = True
                speech_bytes += len(chunk)
                continue

            if speech_started:
                speech_bytes += len(chunk)
                continue

            candidate_speech_bytes += len(chunk)
            if _bytes_to_audio_ms(candidate_speech_bytes, sample_rate) >= min_speech_ms:
                speech_started = True
                speech_bytes = candidate_speech_bytes
            continue

        if not speech_started:
            if vad_enabled:
                candidate_speech_bytes = 0
                if (
                    initial_silence_timeout_ms is not None
                    and _bytes_to_audio_ms(bytes_read, sample_rate) >= initial_silence_timeout_ms
                ):
                    finish_reason = "initial_timeout"
                    break
            continue

        silence_after_speech_bytes += len(chunk)
        if not vad_enabled:
            continue

        enough_speech = _bytes_to_audio_ms(speech_bytes, sample_rate) >= min_speech_ms
        enough_silence = (
            _bytes_to_audio_ms(silence_after_speech_bytes, sample_rate) >= silence_after_speech_ms
        )
        if enough_speech and enough_silence:
            finish_reason = "silence_after_speech"
            break

    if finish_reason not in {"silence_after_speech", "initial_timeout", "no_audio"} and (
        bytes_read >= target_bytes or time.monotonic() >= deadline
    ):
        finish_reason = "no_audio" if not speech_started else "timeout"

    captured_audio = b"".join(chunks)
    if vad_enabled and not speech_started:
        captured_audio = b""

    silence_bytes = silence_after_speech_bytes if speech_started else bytes_read
    average_rms = (rms_weighted_sum / bytes_read) if bytes_read else 0.0

    return CaptureResult(
        audio_bytes=captured_audio,
        bytes_read=bytes_read,
        duration_ms=_bytes_to_audio_ms(bytes_read, sample_rate),
        speech_started=speech_started,
        finish_reason=finish_reason,
        silence_ms=_bytes_to_audio_ms(silence_bytes, sample_rate),
        average_rms=average_rms,
        max_rms=max_rms,
    )


def _bytes_to_audio_ms(audio_bytes_length: int, sample_rate: int) -> int:
    if sample_rate <= 0:
        return 0
    return int((audio_bytes_length / (sample_rate * 2)) * 1000)
