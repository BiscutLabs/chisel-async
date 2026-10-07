# Dual-rail logic and completion

Return-to-zero dual rail encodes every payload bit using `zero` and `one` rails.
The pair `(zero, one)` is `00` for spacer, `10` for zero, `01` for one; `11` is
illegal. Read [protocol contracts](contracts.md#return-to-zero-dual-rail) before
writing a driver. Ordinary bundled-data Boolean expressions are not dual-rail
completion logic.

## Storage and indication

`DualRailStrongBuffer[T]` waits for a complete valid input word before producing
output data. It retains that data until the downstream consumer acknowledges and
the source has fully returned to spacer. Output spacer is also strongly indicated.
This is a half-buffer protocol, not the fully decoupled long-hold contract.

The older `DualRailBuffer[T]` uses per-bit Muller storage and a stateful completion
tree. It is useful for the completion probe, but rails may appear before the entire
word is valid. A fork also forwards rails without adding strong word indication.
Choose storage according to the surrounding indication requirements.

Completion must retain state during partial spacer return. A combinational
all-bits-present AND can fall on the first returning bit and acknowledge spacer
too early. The library uses direct N-input/asymmetric C-element primitives where
the topology requires their atomic semantics.

## Bounded DIMS functions

`DualRailFunction[A, B](inGen, outGen, table, timing, domain)` implements a complete
small truth table using delay-insensitive minterm synthesis (DIMS), followed by
strong storage. It accepts **one to four total packed input bits**. Table size is
exactly `2^inputWidth`; entry `i` specifies the output bit pattern for packed input
`i`. Results must fit the known positive output width. Packing follows Chisel's
`asUInt`/`asTypeOf` order, including nested payloads and two's-complement bit
patterns for signed leaves.

Every minterm includes all inputs, even logically redundant ones. Removing an
apparently redundant input can change valid or spacer indication. Construction is
exponential, so this is a bounded functional catalog, not an arbitrary-width
automatic QDI compiler.

Convenience components include NOT/AND/OR/XOR, Boolean select, and a full adder.
For the full adder, input bits 0/1/2 encode `a`, `b`, `carryIn`; output bits 0/1
encode `sum`, `carryOut`. `DualRailSelect` is a Boolean function selecting one of
two input bits; `DualRailDemux[T]` routes a token to one of two output channels.
They solve different problems.

## Compose rails and convert encodings

`DualRailFork` broadcasts to every branch and waits for all acknowledgements in
both phases. `DualRailJoin` pairs independently stored operands. `DualRailDemux`
captures `Selected[T]` and leaves the unselected output at spacer.
`DualRailMerge` requires serialized complete valid/spacer handshakes; it contains
no arbitration. Use an explicit arbitrated boundary for competing sources.

`FourPhaseToDualRail` stores the bundled token before presenting rails.
`DualRailToFourPhase` waits for complete valid rails, holds decoded binary data
through return, and waits for complete spacer before rearming. Both advertise
one buffered token and require `BundledTiming.Digital` plus `PhaseTiming`.

For decoding, `matchedDelay > phase.cells.max + dataDelay.max` guards the binary
latch plus downstream data path. Return guards prevent a new word from reaching
a latch that has not reopened. The separate [timing guide](timing-and-export.md)
explains why the QDI-side indication contract does not remove the bundled-side
timing obligation.

## Assumptions and tests

`QdiTiming(DelayBounds(...))` records independent positive cell bounds; it does not
introduce a bundled-data relative-delay inequality. The current experiment assumes
atomic cells, ideal wire forks, monotonic RTZ traffic and coordinated reset.
Physical QDI implementation still needs an appropriate cell mapping and fork
assumptions; passing these digital tests is not physical QDI certification.

Test all input values for small tables, then separately test partial valid and
spacer waves, different per-cell delays, stalled consumers, repeated values and
reset in each phase. Track delivered outputs even when upstream acknowledgement
has not arrived. A functional truth-table test alone cannot establish indication.
The [QDI examples](examples.md) and repository event campaigns exercise these
distinct properties with independent rail observers and deliberately faulty RTL.
