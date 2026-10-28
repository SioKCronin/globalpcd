"""Free-running OpenLIFU sonication: the monitor sits beside the trigger.

Pulses stay on the published pulse-interval clock. The monitor may call
abort. It is not given a way to start the transmitter.
"""

from __future__ import annotations

from pcd import FeedbackConfig, PCDFeedbackEngine, SignalParams, iter_signals
from pcd.monitor import OpenLIFUTiming, request_stop, run_beside_trigger


class Sonication:
    """Controller stub. abort() is the only method handed to the monitor."""

    def __init__(self) -> None:
        self.abort_calls = 0
        self.tx_started = False

    def abort(self) -> None:
        self.abort_calls += 1

    def start_trigger(self) -> None:
        self.tx_started = True


def _frames(regimes, n: int, timing: OpenLIFUTiming | None = None):
    timing = timing or OpenLIFUTiming()
    params = SignalParams.lifu(f_drive=timing.f_drive_hz)
    return [
        signal
        for _i, _t, signal in iter_signals(regimes, params, n_frames=n)
    ], params


def _engine(params: SignalParams, *, deadline_ms: float) -> PCDFeedbackEngine:
    return PCDFeedbackEngine(
        FeedbackConfig(
            fs=params.fs,
            f_drive=params.f_drive,
            localize_every_n=0,
            deadline_ms=deadline_ms,
        )
    )


class TestOpenLIFUTiming:
    def test_published_sequence(self):
        timing = OpenLIFUTiming()
        assert timing.f_drive_hz == 400e3
        assert timing.pri_s == 0.1
        assert timing.min_pri_s == 0.01
        assert timing.pulse_duration_s == 5e-3
        assert timing.pulses_per_train == 300

    def test_window_is_the_calibrated_preset(self):
        """Their pulse is 5 ms. The reading uses the 200 µs preset."""
        frames, params = _frames("stable", 1)
        assert params.duration == 200e-6
        assert frames[0].shape == (int(params.fs * params.duration),)
        assert params.duration < OpenLIFUTiming().pulse_duration_s


class TestBesideRun:
    def test_reading_finishes_inside_minimum_interval(self):
        timing = OpenLIFUTiming()
        frames, params = _frames(["none", "stable"], 12, timing)
        engine = _engine(params, deadline_ms=timing.min_pri_s * 1e3)
        session = Sonication()
        events = run_beside_trigger(
            engine,
            frames,
            pri_s=timing.min_pri_s,
            on_abort=session.abort,
        )
        assert session.abort_calls == 0
        assert session.tx_started is False
        assert len(events) == 12
        assert all(e.reading is not None and not e.missed for e in events)
        assert all(e.reading.latency_ms < timing.min_pri_s * 1e3 for e in events)
        assert all(
            e.reading.timestamp == e.pulse_index * timing.min_pri_s for e in events
        )

    def test_stable_train_does_not_abort(self):
        timing = OpenLIFUTiming()
        frames, params = _frames(["none", "stable"], 6, timing)
        engine = _engine(params, deadline_ms=timing.pri_s * 1e3)
        session = Sonication()
        events = run_beside_trigger(
            engine,
            frames,
            pri_s=timing.pri_s,
            on_abort=session.abort,
        )
        assert session.abort_calls == 0
        assert session.tx_started is False
        assert len(events) == 6
        assert all(not e.missed and not e.abort_requested for e in events)
        assert [e.reading.regime.value for e in events] == [
            "none",
            "stable",
            "none",
            "stable",
            "none",
            "stable",
        ]

    def test_inertial_aborts_and_drops_the_rest(self):
        timing = OpenLIFUTiming()
        frames, params = _frames(["none", "stable", "inertial", "stable"], 4, timing)
        engine = _engine(params, deadline_ms=timing.pri_s * 1e3)
        seen = {"n": 0}
        real = engine.process_frame

        def counting(data, ts):
            seen["n"] += 1
            return real(data, ts)

        engine.process_frame = counting
        session = Sonication()
        events = run_beside_trigger(
            engine,
            frames,
            pri_s=timing.pri_s,
            on_abort=session.abort,
        )
        assert seen["n"] == 3
        assert session.abort_calls == 1
        assert session.tx_started is False
        assert [e.pulse_index for e in events] == [0, 1, 2]
        assert events[2].abort_requested
        assert events[2].reading.regime.value == "inertial"
        assert events[2].reading.confidence >= 0.5
        assert request_stop(events[0].reading) is False
        assert request_stop(events[1].reading) is False

    def test_overrun_misses_the_next_pulse_without_replaying_it(self):
        timing = OpenLIFUTiming()
        frames, params = _frames("stable", 5, timing)
        engine = _engine(params, deadline_ms=1_000.0)
        session = Sonication()
        events = run_beside_trigger(
            engine,
            frames,
            pri_s=timing.pri_s,
            on_abort=session.abort,
            busy_s=lambda _reading: 0.25,
        )
        assert session.abort_calls == 1
        assert len(events) == 2
        assert events[0].missed is False
        assert events[0].reading is not None
        assert events[0].reading.regime.value == "stable"
        assert events[1].missed is True
        assert events[1].reading is None
        assert events[1].abort_requested is True
        assert events[1].due_s == timing.pri_s

    def test_no_reading_requests_abort(self):
        frames, params = _frames("stable", 3)
        engine = _engine(params, deadline_ms=0.0)
        session = Sonication()
        events = run_beside_trigger(
            engine,
            frames,
            pri_s=OpenLIFUTiming().pri_s,
            on_abort=session.abort,
        )
        assert session.abort_calls == 1
        assert len(events) == 1
        assert events[0].reading.status.value == "no_reading"
        assert events[0].abort_requested is True

    def test_rejects_nonpositive_interval(self):
        frames, params = _frames("none", 1)
        engine = _engine(params, deadline_ms=1_000.0)
        try:
            run_beside_trigger(engine, frames, pri_s=0.0, on_abort=lambda: None)
        except ValueError as exc:
            assert "pri_s" in str(exc)
        else:
            raise AssertionError("expected ValueError")

    def test_empty_train(self):
        _frames_unused, params = _frames("none", 1)
        engine = _engine(params, deadline_ms=1_000.0)
        session = Sonication()
        assert run_beside_trigger(
            engine, [], pri_s=0.1, on_abort=session.abort
        ) == []
        assert session.abort_calls == 0
