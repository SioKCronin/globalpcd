# Partnership: cavitation sensing beside a therapy controller

globalPCD is an MIT-licensed cavitation safety monitor for focused-ultrasound
controllers. OpenLIFU is the first platform this note is written for. The same
contract is meant for any controller that can hand over a receive window and
accept a reading back.

The controller plans and delivers the sonication. globalPCD listens to the
receive waveform from that sonication and reports what it heard. It does not
choose the next pulse, program a solution, or enable high voltage.

This software is research-only and not FDA-evaluated. Labels below are
synthetic-calibrated. They are not a claim about tissue, harm, or regulatory
clearance.

## How the two sides meet

| | Therapy controller | globalPCD |
|--|--------------------|-----------|
| Owns | Solution, delays, apodization, high-voltage rails, trigger, pulse policy | Regime, confidence, optional location, measured latency |
| Calls | `process_frame` on its own clock, or subscribes to readings | `PCDFeedbackEngine` |
| Does not do | Hear cavitation. The public OpenLIFU SDK drives TX7332 transmit and HV. Console telemetry (temperature, voltage, power) is not a receive waveform. | `start_sonication`, `set_solution`, or arming TX. `OpenLIFUTriggerClock` is observe-only unless a bench explicitly passes `allow_tx_start=True`. |

The object that crosses the boundary is a versioned [`PCDReading`](PCDREADING.md)
(schema **1.1.0**). Machine-readable form:
[`pcdreading.schema.json`](pcdreading.schema.json).

A reading says `none` / `stable` / `inertial` / `mixed`, how sure, an optional
location, and how long the classification took. `no_reading` means the deadline
was missed or the frame failed. The controller should hold. It should not
replay a previous frame as live.

Suggested mapping for neuromodulation safety, still research-only, policy
remaining with the platform:

- `inertial` at high confidence → interlock or step-down, beside existing
  mechanical-index limits
- `no_reading` → hold
- `none` → continue under those existing limits
- `stable` → caution

Minor schema versions only add optional fields. Consumers ignore unknown
fields. An Openwater-specific fork of the schema is the outcome we want to
avoid; field names a controller needs can fold into 1.x.

Two call styles already exist:

- **Pull.** The run loop calls `PCDFeedbackEngine.process_frame(channel_data, trigger_timestamp)` between pulse blocks and reads the result before the next block.
- **Subscribe.** The controller registers a callback and reacts when a reading is emitted.

Which of those fits the sonication loop is a question for the platform: is
there time between pulse blocks for a synchronous check, or does the monitor
have to run beside the loop and only publish the latest reading?

## What a recording has to contain

Phase 1 is one PCD hydrophone and a DAQ. One frame is one receive window for
one pulse. A session is a sequence of those frames. `HydrophoneFileSource`
treats a whole WAV or 1-D `.npy` as a single window; many pulses belong in
repeated `process_frame` calls, or in a `FileReplaySource` array with
`layout="frames"` and shape `(N_frames, N_samples)`.

Each window needs four things or the reading is not about that pulse:

| Piece | What we assume | Why |
|-------|----------------|-----|
| `channel_data` | 1-D samples, float. WAV integer PCM is scaled by the dtype full scale (int16 → 32768), not by the file peak. Float WAV and `.npy` are used as stored. | This is the only acoustic input. |
| `fs` | Sample rate in Hz. A WAV header supplies it. A `.npy` does not; the caller passes `fs`. | Spectral bins are computed from `fs`. |
| `f_drive` | Therapy drive frequency in Hz, passed in on `FeedbackConfig`. The synthetic LIFU preset used in tests is 200–650 kHz, default 500 kHz. | Subharmonic, ultraharmonic, and harmonic bands are placed at `f_drive`. |
| `trigger_timestamp` | Seconds on a clock shared with the sonication, ideally the TX trigger time for this window. | The reading stores this value unchanged. It is how a later log lines the regime up with the pulse. |

The current feature extractor looks for a peak at `f/2` and `3f/2`, the first
three harmonics, and a broadband level from 0.1 MHz up to `0.45 * fs`, with
20 kHz bins. A recording whose sample rate does not cover that band will not
show those markers. The test preset samples at 10 MHz for 200 µs. That preset
is a stand-in for a DAQ file, not a hardware requirement and not a claim about
emissions at a real site.

Scale is an open assumption. Thresholds were fit on peak-normalized synthetic
RF, not on calibrated pascals. A quiet file that arrives already in volts or
pressure will not match those absolute amplitudes. The subharmonic check also
requires the peak to clear its local noise floor, which is less sensitive to
gain. A partner file should say what the numbers are (volts, pascals, or
already normalized) so we can either keep them or state the scale factor.

These are not a substitute for the window above:

- A solution JSON, trigger configuration, or `start_sonication()` result. That
  is the delivered pulse, not the received sound.
- Console logs of temperature, voltage, or power.
- A software sleep paced at the PRF. `SoftwarePRFClock` and
  `OpenLIFUTriggerClock.wait` return `time.perf_counter` after an optional
  sleep. They do not observe a TX edge. Built-in file and synthetic sources
  leave `trigger_timestamp` unset, and a session then stores that software
  stamp. A bench recording should carry the DAQ's trigger time instead.

Phase 2, only if a site has a receive array, adds `channel_data` of shape
`(N_elements, N_samples)` and element positions in meters. Location on a
`none` or `unknown` frame is null. A carried location on an active frame is
labeled with `location_frame_id` so the controller can see how old it is.

## What we are asking for

1. A look at where a monitor call belongs in the run loop, and what latency
   per block is acceptable. The engine measures its own `latency_ms` and turns
   a missed `deadline_ms` into `no_reading`.
2. The drive frequencies, pulse lengths, and PRFs actually used at current
   sites, so the synthetic preset and the DAQ sample rate can follow the
   hardware instead of the test defaults.
3. One bench recording, or an anonymised snippet, with the four fields in the
   table. Real-tissue validation is welcome and is not claimed by the
   synthetic path.
4. Whether any partner site already records PCD next to an OpenLIFU sonication.

The reading can be written into the platform's run record (regime, confidence,
latency, `schema_version`) so cavitation status sits with the rest of that
sonication. Pulse policy stays in the controller.
