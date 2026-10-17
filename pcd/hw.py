"""
pcd.hw
------
Hardware-facing ingest: TX-trigger clock + RF receive source → PCDReading.

This layer does **not** drive therapy amplitude or targeting. OpenLIFU (when
present) owns the transmit trigger; RF still comes from a ReceiveSource —
synthetic or file replay until a real passive-array DAQ is wired in.

OpenLIFU's public SDK exposes TX trigger start/stop and PRF configuration,
not per-pulse receive IRQ or multi-channel RF. Until that exists, the clock
is paced at the configured PRF in software, optionally calling
``start_trigger`` / ``stop_trigger`` on a duck-typed TX device.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np

from .beamformer import ArrayGeometry
from .feedback import FeedbackConfig, PCDFeedbackEngine, PCDReading
from .streams import CavitationRegime, iter_array_frames


@dataclass
class ReceiveFrame:
    """One receive window, keyed to a pulse trigger."""

    channel_data: np.ndarray  # (N_samples,) or (N_elements, N_samples)
    # Seconds on the controller clock when this window's pulse fired.
    # None means the source does not know — FeedbackSession then uses the
    # trigger clock's wait() stamp (a software PRF time, not a TX edge).
    trigger_timestamp: float | None = None


@runtime_checkable
class ReceiveSource(Protocol):
    def next_frame(self) -> ReceiveFrame | None:
        """Return the next RF window, or None when the source is exhausted."""


@runtime_checkable
class TriggerClock(Protocol):
    def __enter__(self) -> TriggerClock: ...

    def __exit__(self, exc_type, exc, tb) -> None: ...

    def wait(self) -> float:
        """Block until the next pulse trigger; return timestamp (seconds)."""


class SyntheticReceiveSource:
    """Wrap ``iter_array_frames`` / any ``(id, data)`` iterator as a ReceiveSource."""

    def __init__(self, frames: Iterator[tuple[int, np.ndarray]]) -> None:
        self._frames = frames

    @classmethod
    def from_array(
        cls,
        source_position: tuple[float, float],
        array: ArrayGeometry,
        regimes: Sequence[CavitationRegime] | CavitationRegime = "inertial",
        **kwargs: Any,
    ) -> "SyntheticReceiveSource":
        return cls(iter_array_frames(source_position, array, regimes, **kwargs))

    def next_frame(self) -> ReceiveFrame | None:
        try:
            _frame_id, data = next(self._frames)
        except StopIteration:
            return None
        return ReceiveFrame(channel_data=np.asarray(data, dtype=float))


class FileReplaySource:
    """
    Replay recorded RF from a ``.npy`` file.

    Accepted shapes
    ---------------
    ``(N_frames, N_elements, N_samples)``
        Multi-channel session. Do not pass ``layout``.
    ``(N_frames, N_samples)`` with ``layout="frames"``
        Single-channel session.
    ``(N_elements, N_samples)`` with ``layout="channels"``
        One multi-channel frame (promoted to a 1-frame session).

    A 2-D array is not guessed. ``(N_frames, N_samples)`` and
    ``(N_elements, N_samples)`` can have the same rank and similar sizes
    (a short single-channel session looks like a modest array), so the
    caller has to say which axis is which.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        layout: Literal["frames", "channels"] | None = None,
    ) -> None:
        arr = np.load(Path(path))
        if arr.ndim == 2:
            if layout == "frames":
                arr = arr[:, np.newaxis, :]
            elif layout == "channels":
                arr = arr[np.newaxis, ...]
            else:
                raise ValueError(
                    "2-D RF replay is ambiguous: pass layout='frames' for "
                    "(N_frames, N_samples) or layout='channels' for one "
                    f"(N_elements, N_samples) frame. Got shape {tuple(arr.shape)}."
                )
        elif layout is not None:
            raise ValueError(
                f"layout={layout!r} applies only to 2-D replay files "
                f"(got ndim {arr.ndim})"
            )
        if arr.ndim != 3:
            raise ValueError(
                f"RF replay file must be 2-D or 3-D, got shape {arr.shape}"
            )
        self._frames = np.asarray(arr, dtype=float)
        self._i = 0

    def next_frame(self) -> ReceiveFrame | None:
        if self._i >= self._frames.shape[0]:
            return None
        data = self._frames[self._i]
        self._i += 1
        return ReceiveFrame(channel_data=data)


def load_hydrophone_file(path: str | Path) -> tuple[np.ndarray, float | None]:
    """
    Load a single-element PCD recording.

    ``.wav`` — first channel, full-scale float in about [-1, 1]; returns
    ``(signal, fs)``. Integer PCM is divided by the dtype full scale
    (int16 → 32768), not by the file peak, so a quiet recording stays
    quiet. Float WAV is returned as stored.
    ``.npy`` — 1-D float array; returns ``(signal, None)`` (caller supplies fs).
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".wav":
        from scipy.io import wavfile

        fs, data = wavfile.read(path)
        data = np.asarray(data)
        if data.ndim > 1:
            data = data[:, 0]
        return _wav_to_float(data), float(fs)
    if suffix == ".npy":
        data = np.asarray(np.load(path), dtype=float)
        if data.ndim != 1:
            raise ValueError(
                f"hydrophone .npy must be 1-D (got shape {data.shape}); "
                "use FileReplaySource for multi-channel sessions"
            )
        return data, None
    raise ValueError(f"unsupported hydrophone file type: {path.suffix}")


def _wav_to_float(data: np.ndarray) -> np.ndarray:
    """Map WAV samples to float without peak-normalising."""
    if np.issubdtype(data.dtype, np.floating):
        return np.asarray(data, dtype=np.float64)
    if data.dtype == np.uint8:
        return (data.astype(np.float64) - 128.0) / 128.0
    if np.issubdtype(data.dtype, np.signedinteger):
        # iinfo.min is -2**(nbits-1); dividing by its magnitude maps
        # full-scale negative to -1 and full-scale positive to just under 1.
        scale = -float(np.iinfo(data.dtype).min)
        return data.astype(np.float64) / scale
    raise ValueError(f"unsupported WAV sample dtype: {data.dtype}")


def write_hydrophone_wav(path: str | Path, signal: np.ndarray, fs: float) -> None:
    """Write a 1-D RF window as 16-bit PCM WAV.

    The writer peak-normalises so a quiet synthetic uses the PCM range.
    :func:`load_hydrophone_file` does not peak-normalise on the way back
    in: it converts full-scale integers to ±1.
    """
    from scipy.io import wavfile

    x = np.asarray(signal, dtype=float).ravel()
    peak = np.max(np.abs(x))
    if peak > 0:
        x = x / peak
    pcm = np.clip(x * 32767.0, -32768, 32767).astype(np.int16)
    wavfile.write(Path(path), int(round(fs)), pcm)


class HydrophoneFileSource:
    """
    Single-element ingest: one WAV or 1-D NPY file → one ReceiveFrame.

    This is the phase-1 OpenLIFU-adjacent path (hydrophone + DAQ), not array
    localization.
    """

    def __init__(self, path: str | Path, fs: float | None = None) -> None:
        signal, file_fs = load_hydrophone_file(path)
        resolved = file_fs if file_fs is not None else fs
        if resolved is None:
            raise ValueError("fs is required for .npy hydrophone files")
        self.fs = float(resolved)
        self._frame = ReceiveFrame(channel_data=signal)
        self._done = False

    def next_frame(self) -> ReceiveFrame | None:
        if self._done:
            return None
        self._done = True
        return self._frame


class SoftwarePRFClock:
    """Pace frames at a fixed PRF with no hardware involved."""

    def __init__(self, prf_hz: float = 1.0, *, pace: bool = True) -> None:
        if prf_hz <= 0:
            raise ValueError(f"prf_hz must be > 0, got {prf_hz}")
        self.prf_hz = float(prf_hz)
        self.pace = pace
        self._i = 0
        self._t0 = 0.0

    def __enter__(self) -> "SoftwarePRFClock":
        self._i = 0
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def wait(self) -> float:
        if self.pace:
            target = self._t0 + self._i / self.prf_hz
            delay = target - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
        ts = time.perf_counter()
        self._i += 1
        return ts


class OpenLIFUTriggerClock:
    """
    Sync PCD ingest to an OpenLIFU TX trigger.

    ``tx`` is duck-typed (``start_trigger``, ``stop_trigger``, optional
    ``set_trigger_json``). Pass a real ``LIFUInterface.txdevice`` when
    hardware is present; omit it to run the same PRF software clock.

    Per-pulse RF is **not** read from OpenLIFU — pair this clock with a
    :class:`ReceiveSource`.

    ``wait`` returns a software-clock timestamp (``time.perf_counter``),
    paced at ``prf_hz`` when ``pace`` is true. It does not observe TX
    trigger edges. Built-in receive sources leave
    ``ReceiveFrame.trigger_timestamp`` unset, so :class:`FeedbackSession`
    stores this software stamp on the reading. Pass ``pace=True`` to
    space frames at the PRF; an independently running transmitter is
    not aligned to these stamps. When the DAQ knows the real trigger
    time, set ``trigger_timestamp`` on the frame — that value wins.

    Safety: by default this clock is **observe-only** and never starts the
    transmitter, even when ``tx`` is given. Starting TX is an actuation
    decision that belongs to the therapy platform; pass
    ``allow_tx_start=True`` only in a bench setup where you intend
    globalPCD to arm and stop the trigger.
    """

    def __init__(
        self,
        tx: Any | None = None,
        prf_hz: float = 1.0,
        trigger_json: dict[str, Any] | None = None,
        *,
        allow_tx_start: bool = False,
        pace: bool = True,
    ) -> None:
        if prf_hz <= 0:
            raise ValueError(f"prf_hz must be > 0, got {prf_hz}")
        if trigger_json is not None and not allow_tx_start:
            raise ValueError(
                "trigger_json configures the transmitter; it requires "
                "allow_tx_start=True"
            )
        self.tx = tx
        self.prf_hz = float(prf_hz)
        self.trigger_json = trigger_json
        self.allow_tx_start = allow_tx_start
        self.pace = pace
        self._clock = SoftwarePRFClock(prf_hz, pace=pace)
        self._hw_started = False

    def _stop_tx(self) -> None:
        stop = getattr(self.tx, "stop_trigger", None) if self.tx is not None else None
        if stop is not None:
            stop()

    def __enter__(self) -> "OpenLIFUTriggerClock":
        if self.tx is not None and self.allow_tx_start:
            if self.trigger_json is not None:
                setter = getattr(self.tx, "set_trigger_json", None)
                if setter is None:
                    raise TypeError("tx has no set_trigger_json")
                setter(data=self.trigger_json)
            start = getattr(self.tx, "start_trigger", None)
            if start is None:
                raise TypeError("tx has no start_trigger")
            ok = start()
            if ok is False:
                self._stop_tx()
                raise RuntimeError("OpenLIFU start_trigger() failed")
            self._hw_started = True
        self._clock.__enter__()
        return self

    def wait(self) -> float:
        return self._clock.wait()

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._hw_started:
                self._stop_tx()
                self._hw_started = False
        finally:
            self._clock.__exit__(exc_type, exc, tb)
        return None


def try_openlifu_tx() -> Any | None:
    """
    Return ``LIFUInterface().txdevice`` if openlifu-sdk is installed and a
    TX module is connected; otherwise None (synthetic/file path).
    """
    try:
        from openlifu_sdk import LIFUInterface  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        interface = LIFUInterface()
        connected = interface.is_device_connected()
    except Exception:
        return None
    tx_ok = connected[0] if isinstance(connected, tuple) else bool(connected)
    if not tx_ok:
        return None
    return interface.txdevice


@dataclass
class FeedbackSession:
    """
    Run the feedback engine on a trigger clock + receive source.

    Typical OpenLIFU-shaped loop (TX trigger, synthetic RF)::

        session = FeedbackSession(engine, receive, OpenLIFUTriggerClock(tx, prf_hz=1.0))
        readings = session.run(n_frames=8)

    Each reading's ``timestamp`` is ``ReceiveFrame.trigger_timestamp``
    when the source set one, otherwise the value returned by
    ``trigger.wait()``. For :class:`OpenLIFUTriggerClock` and
    :class:`SoftwarePRFClock` that wait value is a software clock, not
    an observed TX edge. :class:`SyntheticReceiveSource`,
    :class:`FileReplaySource`, and :class:`HydrophoneFileSource` leave
    the frame timestamp unset.
    """

    engine: PCDFeedbackEngine
    receive: ReceiveSource
    trigger: TriggerClock

    def run(self, n_frames: int | None = None) -> list[PCDReading]:
        readings: list[PCDReading] = []
        n = 0
        with self.trigger:
            while n_frames is None or n < n_frames:
                ts = self.trigger.wait()
                frame = self.receive.next_frame()
                if frame is None:
                    break
                stamp = (
                    frame.trigger_timestamp
                    if frame.trigger_timestamp is not None
                    else ts
                )
                readings.append(self.engine.process_frame(frame.channel_data, stamp))
                n += 1
        return readings


def openlifu_demo_session(
    *,
    n_frames: int = 6,
    prf_hz: float = 10.0,
    pace: bool = False,
    tx: Any | None = None,
) -> list[PCDReading]:
    """Convenience: synthetic array RF paced by an OpenLIFU-shaped trigger clock."""
    array = ArrayGeometry.linear(n_elements=8, pitch=1.5e-3)
    engine = PCDFeedbackEngine(
        FeedbackConfig(
            fs=25e6,
            f_drive=1e6,
            localize_every_n=2,
            localize_grid_points=25,
            deadline_ms=5_000.0,
            x_range=(-8e-3, 8e-3),
            z_range=(25e-3, 50e-3),
        ),
        array=array,
    )
    receive = SyntheticReceiveSource.from_array(
        (1e-3, 35e-3),
        array,
        regimes=["none", "stable", "inertial"],
        fs=25e6,
        duration=60e-6,
        snr_db=35,
        n_frames=n_frames,
    )
    trigger = OpenLIFUTriggerClock(tx=tx, prf_hz=prf_hz, pace=pace)
    return FeedbackSession(engine, receive, trigger).run(n_frames=n_frames)
