# Reading verification traces

Chisel-async's repository tests save event traces alongside pass/fail summaries
so you can inspect what happened during a run. Formats differ between test suites;
check the schema or header to choose the right reader. Use the transaction counts
and traces together to check that the expected transfers occurred.

## Functional and timing JSONL

Functional/timed cocotb cases write `<case>.trace.jsonl` and `<case>.evidence.json`.
Evidence `schema: 1` selects the packaged
[trace-v1 schema](../src/main/resources/chiselasync/trace-v1.schema.json). Example:

```json
{"index":1,"time_fs":1001,"time_ps":1,"kind":"edge","channel":"out","signal":"req","value":1}
```

Indices start at one and are contiguous. `time_fs` is a nonnegative signed 64-bit
integer and never decreases. `time_ps` must equal `time_fs // 1000`; it cannot
represent sub-picosecond ordering. Equal timestamps retain observer order through
their indices, without claiming visibility of every simulator delta glitch.

Functional events include offers, edges, acceptance, delivery, data, reset and
violations. Timing events include launch, valid data, capture, delay scheduling
and reset epochs. Evidence includes activity/counters, trace length and hash.
Readers validate cross-field relationships, exact case inventories and expected
fault diagnostics in addition to JSON Schema structure.

## Phase campaign text traces

The separate phase format begins `PHASE_TRACE|2`. Settled records contain
`time_fs|reset|channel|req|ack|data_hex|zero_hex`. Two-phase completion uses the
payload retained at the request transition even if idle data causally changes
within the completion sample.

At reset boundaries and final drain, `COUNTS|epoch|channel|count` records independent
HDL completion-edge counters for public and registered internal channels. Readers
require one witness per boundary/epoch and agreement with decoded completions,
including zero counts. Two-phase counts both acknowledgement polarities; other
protocols count rising acknowledgement. Missing witnesses or omitted transfers fail.

Finite-prefix negative controls can end at the intended violation without a final
drain, but need a passing active baseline and their specific diagnostic. Historical
traces must be read with their recorded checker revision.

## Other campaigns

Controller event graphs, QDI/architecture/boundary benches and ChiselSim have their
own evidence formats. Use their runners/readers, not the JSONL reader by analogy.
Record source/checker versions when adapting them. The
[example index](examples.md) identifies the campaign for each design family;
[testing](testing.md) explains what counters and independent oracles establish.
