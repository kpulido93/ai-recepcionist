from __future__ import annotations

from vicidial_vosk_cobranza_ivr import audio


def test_calculate_rms_returns_zero_for_empty_audio() -> None:
    assert audio.calculate_rms(b"") == 0.0


def test_calculate_rms_detects_signal_above_threshold() -> None:
    rms = audio.calculate_rms(b"\xff\x7f" * 400)

    assert rms > 150.0


def test_capture_eagi_audio_reads_from_fd_until_eof(monkeypatch) -> None:
    chunks = iter([b"\x01\x02", b"\x03\x04", b""])

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio(fd=3, listen_seconds=1, sample_rate=8000)

    assert captured == b"\x01\x02\x03\x04"


def test_capture_eagi_audio_result_returns_silencio_when_only_silence(monkeypatch) -> None:
    chunks = iter([b"\x00\x00" * 800] * 10)

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio_result(
        fd=3,
        listen_seconds=1,
        sample_rate=8000,
        chunk_size=1600,
        vad_enabled=True,
        min_speech_ms=250,
        silence_after_speech_ms=700,
        rms_speech_threshold=250.0,
    )

    assert captured.audio_bytes == b""
    assert captured.speech_started is False
    assert captured.finish_reason == "no_audio"
    assert captured.silence_ms == 1000
    assert captured.average_rms == 0.0
    assert captured.max_rms == 0.0


def test_capture_eagi_audio_result_stops_after_silence_post_speech(monkeypatch) -> None:
    speech_chunk = b"\xff\x7f" * 800
    silence_chunk = b"\x00\x00" * 800
    chunks = iter([speech_chunk] * 3 + [silence_chunk] * 7)

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio_result(
        fd=3,
        listen_seconds=2,
        sample_rate=8000,
        chunk_size=1600,
        vad_enabled=True,
        min_speech_ms=250,
        silence_after_speech_ms=700,
        rms_speech_threshold=250.0,
    )

    assert captured.speech_started is True
    assert captured.finish_reason == "silence_after_speech"
    assert captured.duration_ms == 1000
    assert captured.silence_ms == 700
    assert captured.average_rms > 0.0
    assert captured.max_rms > captured.average_rms
    assert len(captured.audio_bytes) == 16000


def test_capture_eagi_audio_result_times_out_when_speech_is_continuous(monkeypatch) -> None:
    speech_chunk = b"\xff\x7f" * 800
    chunks = iter([speech_chunk] * 10)

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio_result(
        fd=3,
        listen_seconds=1,
        sample_rate=8000,
        chunk_size=1600,
        vad_enabled=True,
        min_speech_ms=250,
        silence_after_speech_ms=700,
        rms_speech_threshold=250.0,
    )

    assert captured.speech_started is True
    assert captured.finish_reason == "timeout"
    assert captured.silence_ms == 0
    assert captured.average_rms > 0.0
    assert captured.max_rms == captured.average_rms
    assert len(captured.audio_bytes) == 16000


def test_capture_eagi_audio_result_returns_no_audio_when_speech_is_too_short(monkeypatch) -> None:
    speech_chunk = b"\xff\x7f" * 800
    silence_chunk = b"\x00\x00" * 800
    chunks = iter([speech_chunk, speech_chunk, silence_chunk, silence_chunk, b""])

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio_result(
        fd=3,
        listen_seconds=1,
        sample_rate=8000,
        chunk_size=1600,
        vad_enabled=True,
        min_speech_ms=250,
        silence_after_speech_ms=700,
        rms_speech_threshold=250.0,
    )

    assert captured.audio_bytes == b""
    assert captured.speech_started is False
    assert captured.finish_reason == "no_audio"


def test_capture_eagi_audio_result_with_vad_disabled_preserves_previous_behavior(
    monkeypatch,
) -> None:
    speech_chunk = b"\xff\x7f" * 800
    silence_chunk = b"\x00\x00" * 800
    chunks = iter([speech_chunk, silence_chunk, b""])

    class FakeMonotonic:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            self.value += 0.01
            return self.value

    monkeypatch.setattr(audio.os, "name", "posix")
    monkeypatch.setattr(audio.time, "monotonic", FakeMonotonic())
    monkeypatch.setattr(audio.select, "select", lambda readers, _w, _x, _t: (readers, [], []))
    monkeypatch.setattr(audio.os, "read", lambda _fd, _size: next(chunks))

    captured = audio.capture_eagi_audio_result(
        fd=3,
        listen_seconds=1,
        sample_rate=8000,
        chunk_size=1600,
        vad_enabled=False,
        min_speech_ms=250,
        silence_after_speech_ms=700,
        rms_speech_threshold=250.0,
    )

    assert captured.audio_bytes == speech_chunk + silence_chunk
    assert captured.finish_reason == "timeout"
    assert captured.speech_started is True
