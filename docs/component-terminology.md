# Component terminology and chisel-click comparison

Chisel-async uses the component names in Sparsø and Furber's
[asynchronous circuit tutorial, figure 3.3](https://www.inf.pucrs.br/~calazans/graduate/SSD/Bibliography/Sparso-Furber-Short.pdf):
fork, join, exclusive merge, controlled multiplexer (MUX), demultiplexer (DEMUX),
storage, and function block. These names describe what a component does with
tokens. Components with the same name can differ in storage, protocol and timing,
so the tables below explain those differences.

| Term | Token-level meaning | Our implementation |
| --- | --- | --- |
| Fork | Send each input token to every branch | `FourPhaseFork`: unbuffered broadcast; both acknowledgement phases wait for all branches |
| Registered fork | Store transformed branch values, then broadcast | `FourPhaseRegFork[A,B,C]`: one shared long-hold slot, two result types, all branches empty after reset |
| Join / rendezvous | Pair one token from each input | `FourPhaseJoin`: one operand buffer per input, ordered pairing |
| Exclusive merge | Forward already mutually exclusive inputs | `FourPhaseMerge`: one output slot; callers serialize complete handshakes |
| Arbiter | Choose among competing requests | `FourPhaseArbiter`: MUTEX, return interlocks, and buffered merge |
| Controlled multiplexer | Synchronize a selector with only its chosen input | `FourPhaseMux`: selector token on `select`, one selector slot and one output data slot; unselected offers wait |
| Demultiplexer | Route one token to one selected output | `FourPhaseDemux`: one stored `Selected[T]` token carries both routing index and data |
| Function block | Apply a pure payload transformation | `FourPhaseStage` combines transformation **and storage**; it is not an unbuffered function block |
| Muller C-element | Change on input unanimity; retain state on disagreement | `CElement` for two inputs; `AsymmetricCElement` with common-only inputs for N inputs |
| MUTEX | Resolve competing requests without simultaneous grants | `Mutex` supplies a finite digital model; physical arbitration requires a technology macro |
| Matched delay | Make control arrival follow worst-case data arrival | Bundled timing guards describe the obligation; `#delay` models do not implement it in silicon |

`FourPhaseSelect` and `TwoPhaseSelect` are deprecated compatibility names for
`FourPhaseDemux` and `TwoPhaseDemux`. `Selected[T]` remains the routing-tag payload.
`DualRailSelect` is a Boolean DIMS selection function over three input bits: it
indicates all inputs and is not a controlled channel multiplexer. There is no
implicit arbitration in any mux or demux.

## How this compares with chisel-click

The table below compares chisel-async with
[chisel-click revision ae87f671](https://github.com/KasperHesse/chisel-click/tree/ae87f671bce101a22ea3ec40ad0e9e18a8cc3a28).
It covers the shared operations and explains where their behavior differs.
Chisel-async also includes dual-rail components, clocked bridges, timing metadata
and tools for testing and export.

| chisel-click API / concept | chisel-async counterpart | Equivalence and remaining differences |
| --- | --- | --- |
| `BistableMutex`, `RGDMutex`, `Arbiter` | `Mutex`, `FourPhaseArbiter`, `TwoPhaseArbiter` | Same arbitration role; different controller and digital model. No analog resolution guarantee |
| `DelayElement` | `DelayLine`, control delay cells, `BundledTiming`, ASIC bindings | Model propagation and physical matched delays are distinct. No supplied FPGA delay backend or characterized ASIC library |
| `Demultiplexer` | `FourPhaseDemux`, `TwoPhaseDemux` | Captures an embedded routing tag. chisel-click has a separate selector channel; a join/transform can combine separate data and selector tokens here, adding operand storage |
| `Multiplexer` | `FourPhaseMux`, `TwoPhaseMux` | Explicit selector channel, selected-input-only consumption. Ours buffers selector and output and allows unselected pending offers; upstream documents an input-overlap restriction |
| `Fork` | `FourPhaseFork`, `TwoPhaseFork` | Broadcast with aggregate acknowledgement. Our basic fork has homogeneous outputs; heterogeneous transformation plus storage uses RegFork |
| `RegFork` | `FourPhaseRegFork`, `TwoPhaseRegFork` | Different result types and one input transaction. Long-hold composition, not a fused Click circuit; independent branch initialization/phase settings are absent |
| `Join` | `FourPhaseJoin`, `TwoPhaseJoin` | Ordered rendezvous, but our operands are buffered and the result is a typed pair |
| `JoinReg`, `JoinRegFork` | Join followed by Stage or RegFork | Composition with additional operand storage, not the same fused topology or capacity |
| `Merge` | `FourPhaseMerge`, `TwoPhaseMerge` | Same caller exclusivity obligation, but our output is buffered |
| `FunctionBlock`, `LogicModule` | Typed stage transform / ordinary Chisel datapath | No direct unbuffered matched-delay function-block API; a stage adds storage |
| `HandshakeRegister`, `ClickElement` | Long-hold stage plus phase adapters | **No native Click controller.** Externally two-phase, internally four-phase with guarded conversion |

Chisel-async's two-phase components use four-phase cores with phase adapters.
Their internal transitions, latency, initialization and register behavior therefore
differ from chisel-click's native Click circuits. A native Click implementation
would need its own controller timing contract and delay tests.

For current constructors use the [catalog](components.md); for a controlled loop,
run the [GCD example](examples.md#gcd-with-controlled-feedback).
