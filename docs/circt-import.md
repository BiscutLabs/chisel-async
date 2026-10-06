# Packaged model import

Use the scalar continuous-assignment delay form `assign #DELAY_FS q = ...` in the control gate, asymmetric C-element and closing latch models. The equivalent parenthesized form `assign #(DELAY_FS)` is rejected by the pinned `circt-verilog` from firtool 1.160.0 as an unsupported rise/fall/turn-off delay. This is an importer syntax limitation; the scalar model delay and inertial semantics are unchanged. Procedural nonblocking-assignment delays are a different syntax and are not part of this change.

`verification/test_model_import.py` invokes the actual importer on all three packaged sources with zero and 1000 fs delays. It requires an emitted hardware module and an LLHD delay with the exact specified value. Three mutated sources restore the parentheses and must reproduce the specific importer diagnostic. All nine checks pass locally on native Windows and WSL Linux, and in [native Windows/Ubuntu CI](https://github.com/BiscutLabs/chisel-async/actions/runs/37411950865) at commit `3fd0980`. These tests run in the one-command qualification suite; missing or mismatched import tools fail the lane.

Successful import is not an equivalence or simulation qualification of arbitrary CIRCT passes. The independent Icarus primitive and controller campaigns continue to check digital behavior.
