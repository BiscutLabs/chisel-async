// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Each adapter cell may independently take any delay within cells. The explicit
  * return guard keeps a new token behind closure/reopening of phase/data latches.
  * Ideal wires and zero latch aperture; not physical characterization.
  */
final case class PhaseTiming(cells: DelayBounds, returnDelay: ModelTime) {
  require(cells.min.fs > 0, "phase adapters require positive cell bounds")
  require(returnDelay.fs > cells.max.fs, "phase return guard must exceed maximum cell delay")
}
