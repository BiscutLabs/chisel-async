# GF180 trial adapters

Optional companion tooling; no PDK is downloaded or included in the library.
Start with the [reference guide](../../docs/gf180-reference.md).

- `prepare.py`: trial standard-cell adapters plus an exhaustive missing-cell list.
- `check_functional.py`: polarity/reset tests against supplied PDK functional views.
- `check_cells.py`: Liberty propagation samples at supplied corners, slew and load.

These scripts do not provide a complete physical backend or qualify custom
C-elements, latch aperture, MUTEX behavior, interconnect or asynchronous hazards.
