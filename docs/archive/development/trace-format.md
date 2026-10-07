# Observation trace v1

> Historical development record. For current usage, read the [user documentation](../../index.md).

Functional and timed cocotb cases retain `<case>.trace.jsonl` plus `<case>.evidence.json`. The evidence object's `schema: 1` selects the packaged `chiselasync/trace-v1.schema.json` envelope. Each nonempty JSONL line is one observation:

```json
{"index":1,"time_fs":1001,"time_ps":1,"kind":"edge","channel":"out","signal":"req","value":1}
```

Indices start at one and are contiguous. `time_fs` is a nonnegative integer no larger than 2^63-1 and must never decrease. `time_ps` is the integer floor of `time_fs / 1000`, retained for compatibility; it cannot determine sub-picosecond ordering. Equal timestamps are legal and their index preserves observer order. This is not a claim of gate-level delta-glitch observation. `kind` is a nonblank string; additional event details are allowed. The executable reader enforces ordering and cross-field relationships that JSON Schema cannot express. Empty traces cannot pass.

Functional observations include `edge`, `offer`, `accepted`, `delivered`, `data`, `reset` and `violation`. Timing observations include `launch`, `data_valid`, `capture`, `capture_sample`, `delay_input`, `delay_delivery` and `reset_epoch`. Evidence identifies the case, status, error, observation count, trace filename and case-specific coverage/token counters. Campaign readers require the exact case inventory, matching trace length, demonstrated activity and a specific diagnostic for fault controls; they retain a SHA-256 of the trace.

This schema covers the existing cocotb observation envelope. Controller STG logs, architecture benches and ChiselSim retain their own versioned campaign formats and are not silently relabelled as this format. Incompatible observation meanings require a new schema version.

## CA-07 phase traces v2

The phase campaign's separate text format begins with `PHASE_TRACE|2`. Settled observations are `time_fs|reset|channel|req|ack|data_hex|zero_hex`. Two-phase completion may share a sample with a causal idle-data update; the oracle completes the previously held payload. It continues to reject observed changes while pending.

Before each coordinated reset and at final drain, `COUNTS|epoch|channel|count` records a separate HDL acknowledgement-edge counter for every public and registered internal channel. Two-phase counters include both polarities; four-phase and dual-rail counters include rising edges. Counters ignore reset transients and restart after each snapshot. Complete replay requires exactly one witness per boundary per epoch and equality with protocol-decoded completions, including zeros. Missing witnesses, selective transaction omission and altered counts fail; one surviving transaction is insufficient. Raw observations and witnesses share the hashed trace. This checks completeness against separately instrumented counters, not against an independent simulator or a coherently corrupted bench.

Finite-prefix negative controls do not require a final drain or completed snapshots, but must activate their specific diagnostic after a separately passing active baseline. Historical phase traces predate v2 and must be replayed with their recorded checker revision.
