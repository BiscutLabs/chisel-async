# GF180 reference flow

Use this optional reference to explore an ASIC mapping with GF180's 7-track
standard cells. It prepares explicit adapters, tests their reset/polarity behavior
against the PDK's functional views, and samples propagation from supplied Liberty
files. The PDK and OpenSTA remain outside the JAR and normal tests.

**This is a partial reference.** The long-hold controller still needs characterized
asymmetric C-elements. Preparation records every missing specialization and exits
unsuccessfully while any are missing. It does not replace a C-element with an
arbitrary feedback expression or claim the pipeline is ready for silicon.

## Prepare the public examples

The standalone quickstart uses the published JAR for both the adder pipeline and
the controlled-mux GCD. From `examples/quickstart`, run:

```text
sbt "runMain PrepareAsicReference build/asic-reference"
```

Use a fresh output directory. This writes each design's simulation export, exact
`required-cells.json`, and `timing-bindings-required.json`. The current pipeline
has eight cell specializations and the GCD has 22. Their timing inventories contain
32 and 115 path/arc checks, plus two and seven relative-order checks respectively.
Preparing these inventories does not require a PDK.

With your own GF180 installation, run from the repository root, substituting the
actual Liberty path:

```text
python integrations/gf180/prepare.py --required examples/quickstart/build/asic-reference/pipeline/required-cells.json --liberty /path/to/gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib --trial-buffer-count 64 --output build/gf180-pipeline
```

The buffer count is an experiment input, not a conversion from femtoseconds to
gates. Output includes `adapters.v` and `reference.json`, with exact keys, pin maps,
source hashes, provenance and missing cells. A partial plan exits with code 2;
inspect its report. Repeat with the GCD inventory in a separate directory.

| Primitive | Reference treatment |
| --- | --- |
| Closing latch | `latrnq_1` per bit, plus explicit gate/reset polarity inverters |
| Request/output buffer | Chosen `buf_1` chain with explicit reset gating |
| Inverter/OR control gate | Standard-cell logic with explicit reset gating |
| Modeled data-delay allowance | Requires the real mapped transform/glue path; never automatically adds another delay chain |
| C-element, MUTEX, toggle or other unsupported specialization | Listed as missing; requires a reviewed technology implementation |

GF180's [resettable latch documentation](https://gf180mcu-pdk.readthedocs.io/en/latest/digital/standard_cells/gf180mcu_fd_sc_mcu7t5v0/cells/latrnq/gf180mcu_fd_sc_mcu7t5v0__latrnq_2.html)
describes its positive enable and active-low reset. The adapter's inverters are
real cells whose delays belong in closure and reset analysis. A matching truth
table alone does not establish those timing properties.

## Check the trial adapters

Use the PDK's functional Verilog files to check transparency, retention, reset,
reopening and gate truth tables:

```text
python integrations/gf180/check_functional.py --reference build/gf180-pipeline --model /path/to/gf180mcu_fd_sc_mcu7t5v0.v --model /path/to/primitives.v --output build/gf180-functional
```

Then sample propagation at explicit input slew and output load. Repeat `--liberty`
for each supplied corner:

```text
python integrations/gf180/check_cells.py --reference build/gf180-pipeline --liberty /path/to/tt.lib --liberty /path/to/ss.lib --liberty /path/to/ff.lib --slew-ns 0.1 --load-pf 0.01 --sta /path/to/sta --output build/gf180-samples
```

Reports retain input hashes, logs and result inventories. Functional checks use
`FUNCTIONAL` views. Propagation samples use Liberty, with reset deasserted and
the latch open. They cover neither extracted interconnect nor latch aperture,
setup/hold, reset recovery, pulse widths or custom-cell hazards.
`PROPAGATION_SAMPLES_COMPLETE` is not timing acceptance.

## What the current experiments establish

The pipeline's four available adapter specializations and the GCD's nine passed
the GF180 functional-view tests. Sampling them at TT 25°C/3.3 V, SS 125°C/3.0 V
and FF −40°C/3.6 V produced 39 adapter/corner observations using OpenSTA 2.7.0,
0.1 ns input slew and 0.01 pF output load. The supplied PDK installation identified
open_pdks revision `40cee970d8a9b7eaea35a34fe7d6068f05721f0a`; reports also hash
the actual Liberty files.

The 64-buffer trial had a minimum control propagation of about **10.33 ns at FF**,
below even the simulation preset's 11 ns request guard. The latch's sampled
minimum data-to-Q at FF was about **0.597 ns**, below the preset's 1 ns lower bound.
These results demonstrate why simulation defaults are not physical cell
specifications. Choose and verify a technology-specific timing policy.

Four pipeline specializations and 13 GCD specializations remain unmapped. Before
accepting either hardware design, supply the missing custom cells and real data
paths, characterize the complete adapters, bind the [mapped timing checks](asic-mapping.md#check-the-mapped-timing-paths),
and complete implementation, extraction and timing-aware functional verification.
MUTEX characterization is a separate requirement for designs using arbitration.
