// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Bounded digital cell experiment, with atomic cells and ideal wire forks.
  * These bounds record the experiment; no relative-delay inequality is inferred.
  */
final case class QdiTiming(cells: DelayBounds) {
  require(cells.min.fs > 0, "QDI digital models require positive cell delays")
}
object QdiTiming {
  def fixed(cell: ModelTime): QdiTiming = QdiTiming(DelayBounds.fixed(cell))
}
