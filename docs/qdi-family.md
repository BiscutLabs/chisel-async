# Bounded RTZ dual-rail family

CA-08 extends the small WCHB/DIMS probes into reusable components. Its scope is digital behavior with atomic primitive cells, positive declared cell delays, monotonic 1-of-2 rails and ideal wire forks. Physical QDI mapping and external specialist sign-off remain separate work. The components and development campaign are implemented; native qualification results are recorded separately from the earlier L1 candidate.

## Design contract

The source alternates complete data and complete spacer. Each bit pair is `00` for spacer, `10` for zero and `01` for one; `11` is illegal. A source holds a complete word until acknowledgement rises, then returns every rail monotonically to zero and waits for acknowledgement to fall. Coordinated reset clears pending work; it never retracts a completed downstream transfer.

The existing `DualRailBuffer` is a WCHB probe: individual output bits can appear before the entire input word. `DualRailStrongBuffer` waits for every input bit before any output rail rises, and for every input bit to return to spacer before any active output rail falls. Completion is stateful in both phases. Its output rails also retain the word until downstream acknowledgement. Output delivery can precede input acknowledgement; reset accounting therefore tracks offered obligations separately from upstream acceptance and never undoes a completed delivery.

The design follows the distinction between strong and weak indication and the DIMS construction described in Sparsø and Furber, [tutorial sections 5.3.2 and 5.5.1, figure 5.10](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf). DIMS uses complete C-element minterms and disjoint OR covers; removing a logically redundant operand can break indication even when the binary truth table stays correct. Implementation source is written independently.

## Component scope

| Component | Contract |
| --- | --- |
| `DualRailStrongBuffer[T]` | Typed one-word half-buffer with all-input valid/spacer indication. A chain of N stages has measured stalled acceptance capacity ceil(N/2) for the tested N=1..6; stage count is not a fully decoupled FIFO depth. |
| Small DIMS function | Explicit finite truth table, bounded to four input bits. Every selected minterm includes every input, including redundant operands. Stored, typed output may differ in width from the input. |
| NOT, AND, OR, XOR | Named small Boolean functions with the same strong indication and storage contract. |
| Two-way value select | Three one-bit operands: both candidate values and the selector participate in both phases, including the unselected value. |
| One-bit full adder | All three inputs indicated; sum and carry form one two-bit output token. |
| Fork | Unbuffered broadcast; both acknowledgement phases wait for every branch. Branch delivery may precede upstream completion. Wire forwarding does not add word-level indication. |
| Join | Pair the next left and right tokens into one typed output. Neither input completes until both are present. No independent operand queue is implied. |
| Two-way demultiplexer | Selection travels in dual-rail form with the payload. Exactly one output receives the token; the other remains spacer. |
| Exclusive merge | Caller serializes complete input handshakes. Overlap is an assumption violation, not arbitration. |

## API and exported intent

All components live in `chiselasync.qdi` and require `QdiTiming`. For example:

```scala
import chisel3._
import chiselasync.metadata.{DelayBounds, ModelTime, QdiTiming}
import chiselasync.qdi.DualRailFunction

val timing = QdiTiming(DelayBounds(
  min = ModelTime.ps(1000), max = ModelTime.ps(10000), model = ModelTime.ps(3000)))
// Packed two-bit input to a one-bit parity result; every input is indicated.
class Parity extends DualRailFunction(
  UInt(2.W), Bool(), Seq(0, 1, 1, 0).map(BigInt(_)), timing)
```

Use `asyncChild` to inherit the parent reset domain and `DualRail.connect` for checked connections. `DualRailFunction[A,B]` follows Chisel packing order and accepts a complete table of 2^inputWidth unsigned encoded results. Input width is deliberately limited to 1..4 bits because complete DIMS minterms grow exponentially. Output width must be known and positive. The named classes are `DualRailNot`, `DualRailAnd`, `DualRailOr`, `DualRailXor`, `DualRailSelect` and `DualRailFullAdder`; the last packs sum into bit 0 and carry into bit 1. `DualRailJoin`, `DualRailDemux` and `DualRailMerge` use the typed contracts in the table above.

The `qdi-digital-v1` descriptor records channel bindings, indication, component kind, positive per-cell delay bounds, atomic cells, ideal zero-skew wire forks, monotonic RTZ signaling and coordinated quiescent reset. Exclusive merge additionally records complete-handshake serialization. Each cell's nominal model delay must be inside the bounds; the campaign varies cells independently within them. These bounds describe the digital experiment and do not establish a physical relative-timing inequality.

`ChiselAsyncQdiMarker_v1` carries the descriptor parameters and actual reset/rail/acknowledgement connections. The optimized/deduplicated exporter checks their binding and inventory against the sidecar and reflected port ABI. Consume these constraints before lowering or deleting marker models: the pinned CIRCT importer can specialize away unused passive parameters, so arbitrary downstream retention is not claimed. Fourteen new fixture exports exercise nested payloads, routing and a bundled→dual-rail→unequal fork/join→DIMS sum→bundled composition.

## Verification method

For small cells, enumerate every binary value and independent input arrival/spacer permutation. Hold each partial codeword long enough to expose an early output. Verify data and spacer indication separately, backpressure, repeated words and reset/restart from partial phases. The value oracle uses ordinary Boolean/arithmetic definitions; indication checks operate on observed rails.

Composition checks must cover unequal fork acknowledgements and returns, join pairing with a missing/late operand, alternating and repeated routing choices, exclusive merge serialization, and a mixed bundled/dual-rail composition. Fault controls must specifically reject invalid rails, a dropped input dependency, premature spacer, early fork acknowledgement and wrong output data. A timeout or compile failure is not a substitute for the intended diagnostic.

Optimized export, typed aggregates, negative API cases and consumption from the published JAR are required. Development evidence for this new family does not extend the historical L1 candidate automatically.

## Development evidence and replay

`verification/run_qdi.py` passes 210 cases (14 fixtures × seeds 0..14) with 117,930 deliveries. For one-, two- and three-bit inputs it checks every value and every independent arrival/spacer permutation; the ten-bit aggregate checks all 1,024 values with four forward/reverse order pairs. It does not enumerate 10!² orders. The fork additionally checks all 36 branch acknowledgement rise/fall order pairs. Strong indication, invalid codes, value results, backpressure, partial-phase reset/restart, internal completion activity and token conservation are checked from actual emitted RTL traces.

The generic four-input table is exercised inside the duplicated-operand composition, over that example's reachable operand pairs. This is not exhaustive independent four-input coverage of every possible user table. The earlier four-input DIMS reference has its own exhaustive rail-order experiment and remains in the wrapper.

Seven paired controls require the exact diagnostic for wrong output, a dropped minterm dependency, stateless return, early fork acknowledgement, invalid input rails and merge contention during data or acknowledgement return. Four alter actual RTL with the same bench; three deliberately violate the input contract. Each positive companion must pass before its mutant can count. The mixed-encoding composition checks conservation and reset, but does not advertise an exact capacity for the complete network.

`verification/run_qdi_sequences.py` adds 37 directed cases: 24 early source-spacer/pending-next-offer cases across twelve strong fixtures, twelve actual half-buffer chain fill/drain cases (lengths 1..6 under two cell-delay assignments), and reset after output delivery but before input acknowledgement. A paired actual-RTL mutation removes the output's sink-acknowledgement reservation and must fail specifically with `QDI_SOURCE_SPACER_HOLD`. Chain tests check exact stalled acceptance capacity ceil(N/2) and drain 64 tokens per case. The reset case preserves two delivered outputs despite only one completed upstream acceptance. These tests originated in the fresh review and now run in both the wrapper and clean JAR consumer.

Fresh independent reviews found no circuit or verification blocker. A separate reader, without importing the project verification modules, checked all 210 cases, reconstructed the 97,230 declared steady rail sequences across 195 rail-only cases, and checked 2,744,156 root changes for indication and fork ordering. An additional actual-RTL early-fork-return mutant failed specifically with `QDI_FORK_EARLY_RETURN`. These are scoped agent reviews and bounded experiments, not external specialist certification.

The follow-up review independently replayed all 37 sequence cases / 818 deliveries and checked source legality, capacity, reset accounting and the reservation fault's activation. Local review records are retained under `target/ca08-independent-review` and `target/ca08-verification-review`. The independent campaign audit SHA-256 is `6d382a149229094c69ef91229a1b467c8e9c8d260e1e6590c2f669ac8debe825`; the sequence audit SHA-256 is `e3d34228c1e515bf108afe9abfdcc2ba2734504c5b1fbb3150c0dbc1eb30f491`.

Run the complete wrapper with `python tools/qualify.py`. For focused replay after emission:

```text
python verification/run_qdi.py --output target/qdi-new-attempt
python verification/run_qdi_sequences.py --output target/qdi-sequences-new-attempt
```

Both runners require a fresh output directory and retain simulator identity, activity, raw sources, benches, logs, traces and hashes. The wrapper and clean published-JAR consumer include both lanes. Native results and final test inventories are recorded in [qualification status](qualification.md). CA-08 evidence does not retroactively extend the frozen L1 acceptance scope.
