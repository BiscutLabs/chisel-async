# Four-phase composition (CA-06)

> Historical development record. For current usage, read the [user documentation](../../index.md).

The CA-06 family implements FIFO, initialization, broadcast, pairing and exclusive routing on the logical `Channel[T]` API's four-phase binding. All modules have explicit coordinated reset. Storage uses the qualified Furber–Day long-hold stage; no withdrawn controller, hidden clock or implicit arbiter is introduced.

## Components and transaction boundaries

| API | Storage and completion contract |
| --- | --- |
| `FourPhaseFifo[T](gen, depth, timing, initial, cellDelay, domain)` | Exactly `depth` slots, depth at least one. Empty by default. Optional fully specified typed literals are installed in their declared order after every reset; their count cannot exceed capacity. External offers can wait during initialization, but external acceptance starts only after all initial tokens enter the pipeline. Delivered output still reserves its last slot until acknowledgement falls. |
| `InitialTokens[T](gen, initial, timing, cellDelay, domain)` | Nonempty literal sequence, emitted once per reset epoch. `done` rises after the last complete output handshake and stays high until reset. Only digital timing is allowed. This is an initialization source, not a repeated stream or a clock. |
| `FourPhaseFork[T](gen, branches, cellDelay, domain)` | Unbuffered broadcast to at least two outputs. Every branch receives each input once. A C-element waits for all acknowledgements to rise and for all to fall; individual branches can deliver before input acknowledgement. |
| `FourPhaseJoin[A,B](a, b, timing, cellDelay, domain)` | One independently buffered operand on each input. The output `Joined[A,B]` pairs the nth left operand with the nth right operand. The two child capacities are separate operand slots, not two complete output tuples. Nested joins support larger typed groups. |
| `FourPhaseSelect[T](gen, destinations, timing, cellDelay, domain)` | One buffered input `Selected[T]`, containing `index` and `data`. The decoded one-hot choice is captured with the payload. Changing the next input after its previous full handshake cannot redirect the stored token. An out-of-range index while requesting fails with `SELECT_INDEX_OUT_OF_RANGE`. |
| `FourPhaseMerge[T](gen, inputs, timing, cellDelay, domain)` | One buffered output, at least two inputs. The caller serializes **complete input handshakes**, including acknowledgement return. Another input may wait while the previous output is stalled, once the previous input handshake has completed. Overlap fails with `EXCLUSIVE_MERGE_CONTENTION`; no priority is assigned. |

All channel payloads retain their Chisel types and require exact shapes. Initial values must be fully specified Chisel literals, including aggregate literals. Packing occurs only at documented primitive boundaries. Use `asyncChild` to inherit and wire the parent's reset domain; standalone roots intentionally own distinct domains.

Reset cancels undelivered work and reinstalls the declared initialization sequence. It never undoes a completed output delivery. In a partially consumed fork, delivered branches remain delivered and the other branch obligations are aborted. A join can abort a lone accepted operand. An input offer waiting for capacity is not accepted work. Hold reset until all primitive reset values settle, then resume from idle; the fixtures use 1 µs, not a physical reset specification.

## Topology and timing assumptions

The conceptual rendezvous patterns follow chapter 5 of Sparsø's [Introduction to Asynchronous Circuit Design](https://orbit.dtu.dk/en/publications/introduction-to-asynchronous-circuit-design/): fork combines acknowledgements with a C-element, join combines requests with a C-element, and exclusive merge combines requests with OR and routes acknowledgements through per-input C-elements. Our join adds long-hold operand buffers; our merge adds a long-hold output buffer and selects payload while either input request or acknowledgement is high, preserving data through the internal full-return handshake. No reference implementation code was copied.

`cellDelay` is the exact nominal delay of the additional routing/control cells and must be positive. `BundledTiming` retains its independent per-role bounds and strict data/admission/output guards for each storage stage. The select decoder and merge mux are part of their stage's modeled source-to-capture data path. The exported `bundled-data-path-v1` obligations now record that inclusion, rather than leaving it only in prose. Fork payload wiring and join concatenation are ideal wires; select gating uses an explicit atomic AND cell with selection stable throughout the stored transaction. Per-instance control cells remain `ExtModule` boundaries. These assumptions do not qualify ordinary synthesis decomposition, wire skew or physical latch aperture.

Initialization is an independently written monotonic sequencer, not another replacement storage controller. For each token, a sticky C-element records acknowledgement, its request then falls, and a second sticky C-element records acknowledgement return. Only that return enables the next token. Each state can rise once per reset and cannot reopen itself. Payload selection remains on the current literal through acknowledgement return. Its modeled data delay is bounded by the supplied policy and its request has the policy's strictly longer matched delay. A FIFO uses a monitored merge for initial injection and enables external admission after source completion; that merge is the first storage slot, not an extra hidden slot.

Each whole-path descriptor records its source/sink probes, logic role, zero ideal-logic simulation delay, min/max/model budget and the registered delay-cell owner. A passive KIND=3 marker binds the signals and carries those bounds in RTL. Select uses its captured stage input through latch data, including index decode; merge includes every input request, acknowledgement and payload through its mux and shares the downstream storage data budget; initialization binds reset/sequence state through delayed literal data. These are shared budgets, not additive allowances: mapped logic and wires replace the behavioral data-delay placeholder and must satisfy the recorded whole-path maximum. The physical flow must consume/preserve these markers and discharge the timing obligations before removing them; this library does not implement STA or certify a mapped circuit. The resolver checks owner/model agreement, budget equality and active marker bindings, and rejects missing constraints, rehashed budget changes and RTL parameter/wiring corruptions.

The feedback example starts with one initialized value, increments it through a typed stage, and broadcasts each value to an external consumer. External backpressure stops progression. Positive delays avoid a zero-time ring. The fork/join example has unequal branch depths and different transforms, then pairs their results by token position.

The packaged protocol guard is a simulation diagnostic. `SYNTHESIS` removes its checks; it is not a physical exclusion circuit. The export resolver alone uses `CHISEL_ASYNC_MAPPING`, because mapping forces deliberately violate protocols. All behavioral and consumer simulations keep diagnostics enabled.

## Executable examples and tests

Run the complete contributor command:

```text
python tools/qualify.py
```

Focused replay after emitting the [composition examples](../../../examples/src/main/scala/chiselasync/examples/EmitComposition.scala):

```text
python tools/sbt.py "examples/runMain chiselasync.examples.EmitComposition target/generated"
python verification/run_composition.py
python verification/run_composition.py --fixtures fork join --seeds 17
```

The default campaign now requires **3,333 positive cases and ten exact negative controls**, with 348,753 output deliveries. Eleven examples cover depth-one/depth-three FIFOs, full initialization, repeated literals, a 65-bit source, three-way fork/select/merge, heterogeneous join, reconvergence and feedback. Each runs at nominal delays, uniform 1 ns, uniform 10 ns, and 300 sampled per-cell configurations (seeds 3–302). Cell assignment uses the existing xorshift32-v1 generator seeded with `seed+1`, in registered node/primitive order; the source/sink schedule retains its separate LCG. The PRNG source hash and all realized `defparam` overrides are retained. This supersedes the original three-random-configuration LCG cell sweep, whose evidence remains at its recorded commit. Export validation runs once per fixture, and every simulation worker rechecks the export-input/checker hashes; up to four independent fixture workers keep the complete command practical without sharing simulation outputs. Long-hold overrides must fit their exported bounds; additional routing/initialization cells undergo a separately recorded 1–10 ns sensitivity experiment rather than pretending those varied values equal the API's nominal delay. Request matching and output guards remain fixed.

Tests include all 36 fork acceptance/return permutations, 500 ns legal holds, exact full FIFO backpressure, reset of a full FIFO with a pending offer, lone-operand join stalls, changes to the next selection while output stalls, and reset at output offer/acknowledged/return phases with successful restart. Every positive case requires exact delivery and reset counts. The primitive test adds 768 three-vector state/history checks of AND and sticky initialization behavior across two delays. Compiler tests check all typed mappings, a wrong mux-child alias, nested construction probe names and actual CIRCT import of the new scalar-delay AND model.

The passive monitor checks full-handshake data hold and protocol order. A separate external ledger checks queues, pairing, routing, reservation and reset accounting without production state names or equations. Raw traces are replayed outside the simulator, including the intentionally faulty traces. This replay checks evidence consistency; it shares the ledger implementation with the passive monitor and is not an independent oracle. Hand-derived ledger tests and mutated DUTs test the oracle itself.

Required faults are FIFO over-acceptance, early fork acceptance, early fork return, wrong join operand, wrong selected branch, live input data leaking into a stalled selected output, altered initial payload, simultaneous merge requests, merge overlap during return, and invalid selection. Unrelated exceptions, simulator crashes, timeouts, skipped tests or missing activity cannot count as the required rejection. Reports, compiled sources, commands, exact-fs traces, XML, hashes and per-cell assignments remain under `target/verification/composition`; CI retains them. The published-JAR consumer emits its own examples and repeats all eleven nominal cases and all ten controls.

The original 66-case qualifier passed locally on native Windows and in [native Windows/Linux CI run 37429181972](https://github.com/BiscutLabs/chisel-async/actions/runs/37429181972) at implementation commit `e775aaa70cd767256aa614f962203eddc4946cee`. The two retained native artifacts have matching case summaries and checker identities, with checked source/trace/XML hashes and complete consumer inventories. See [qualification status](qualification.md) for the full catalog of checks.

CA-07 internal-boundary observation later found a request-only merge mux releasing data too early during acknowledgement return. The mux now retains selection through that return; the source descriptor includes acknowledgement as well as request and payload. A paired `merge_early_release` mutation checks the original defect. Earlier revision results below remain historical. The CA-07 qualifier reruns all 3,333 CA-06 cases and ten controls with this repair and passes on native Windows/Linux at `af0a427` ([run 37487912661](https://github.com/BiscutLabs/chisel-async/actions/runs/37487912661)); both retained artifacts pass inventory and hash audits.

Development exposed construction-prefix probe naming and inactive mux-probe coverage; both have permanent export regressions. The initial population-count guard expression falsely diagnosed idle vectors in Icarus and was replaced with explicit bit-pair checks. These failures were corrected before the recorded passing campaign.

The expanded campaign passes all 3,333 cases / 348,753 deliveries and ten exact controls locally on Windows and in [native Windows/Linux CI run 37471755038](https://github.com/BiscutLabs/chisel-async/actions/runs/37471755038) at `a07db44c54aaf94f439e4b6dc208decd6dce3166`. Both native hosts pass the complete wrapper, 226 Python tests, 34 Scala API checks, all 40 exports, ChiselSim and the clean-JAR consumer. Audits of both retained artifacts verify complete inventories and source/trace/XML hashes, including the eleven nominal consumer cases and ten controls; composition summaries and checker identities agree. Final validator hardening rejects deletion of every timing declaration. The directed fork-arrival baseline and required `DATA_HOLD` skew rejection also pass on both hosts.

The expanded development suite remains separate from L1 acceptance: freeze new held-out seed/schedule/depth choices and source identities after review, then record every selected result without tuning against those cases. Increasing this regression sample alone cannot close L1.

This is a development regression campaign, not a held-out L1 acceptance or statistical reliability estimate. L0's frozen candidate remains historical evidence at its recorded commit. macOS, arbitration, QDI composition, independent reset domains, physical timing and analog metastability remain outside CA-06's claims.
