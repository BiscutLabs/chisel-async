// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Each adapter cell may independently take any delay within cells. The explicit
  * return guard keeps a new token behind closure/reopening of phase/data latches.
  * historyClosure includes request distribution and the history latch's closing
  * aperture allowance, separately from its data-to-Q delay. requestDelay delays
  * the toggled output (not the four-phase input pulse) past that entire bound.
  * These are digital bounds requiring replacement by characterized mapped paths.
  */
final case class PhaseTiming(cells: DelayBounds, returnDelay: ModelTime,
    historyClosure: DelayBounds, requestDelay: ModelTime) {
  require(cells.min.fs > 0, "phase adapters require positive cell bounds")
  require(returnDelay.fs > cells.max.fs, "phase return guard must exceed maximum cell delay")
  require(requestDelay.fs > historyClosure.max.fs,
    "phase request guard must exceed maximum history closure delay")
}

object PhaseTiming {
  /** Conservative convenience policy; the closure path remains independently sweepable. */
  def apply(cells: DelayBounds, returnDelay: ModelTime): PhaseTiming =
    new PhaseTiming(cells, returnDelay, cells, returnDelay)
}
