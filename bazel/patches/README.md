# Carried patches

Fixes the build needs from other projects until they land there. Each patch
is a change to that project and carries its license, not this repository's.
Each header says what it fixes and how it retires.

| Patch | Applies to | License |
| --- | --- | --- |
| `0001-orfs-gf180-7t-adder-and-latch-maps.patch` | OpenROAD-flow-scripts | BSD-3-Clause |
| `yosys-0001-aiger2-holes-output-order.patch` | Yosys | ISC |
| `yosys-0002-abc-new-script-option.patch` | Yosys | ISC |
| `0001-gnulib-wrapper-headers-use-I-not-isystem.patch` | the Bazel Central Registry's `BUILD.bazel` overlay for Bison | Apache-2.0 |
| `0001-refactor-interval-lookup-operations-icl-54.patch` | Boost.ICL (upstream commit boostorg/icl@7de3f55655) | BSL-1.0 |

The Yosys, Bison and Boost.ICL patches come from
[bazel-orfs](https://github.com/The-OpenROAD-Project/bazel-orfs), which
applies them in its own root module; Bazel honours such overrides only in
the root module, so a project consuming bazel-orfs carries them too.
