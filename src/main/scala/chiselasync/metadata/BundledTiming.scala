// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Declared digital envelope and propagation value emitted for the default model. */
final case class DelayBounds(min: ModelTime, max: ModelTime, model: ModelTime) {
  require(min.fs <= model.fs && model.fs <= max.fs, "model delay must lie within its bounds")
}
object DelayBounds {
  def fixed(value: ModelTime): DelayBounds = DelayBounds(value, value, value)
}
final case class ControlDelays(a: DelayBounds, b: DelayBounds, acknowledge: DelayBounds, longHold: DelayBounds) {
  def values: Seq[DelayBounds] = Seq(a, b, acknowledge, longHold)
  def worst: ModelTime = ModelTime(values.map(_.max.fs).max)
}
object ControlDelays {
  def uniform(value: DelayBounds): ControlDelays = ControlDelays(value, value, value, value)
}

/** Explicit digital timing policy; bounds are not characterized technology timing. */
sealed trait BundledTiming {
  def matchedDelay: ModelTime
  def dataDelay: DelayBounds
  def controls: ControlDelays
  def latchDelay: DelayBounds
  def outputDelay: ModelTime
  def mode: String
}
object BundledTiming {
  /** Ready-to-use digital experiment (1..10 ns cells, 10 ns data budget).
    * Nominal cell delay is 1 ns, request guard is 11 ns, and output guard is 31 ns.
    * Not an ASIC/FPGA speed grade. Physical implementations need characterized bounds.
    */
  val Simulation: Digital = simulation()

  /** Derive strict guards from a cell envelope and whole-path data budget.
    * Controls and latch share the supplied envelope; use [[Digital]] with
    * [[ControlDelays]] when individual cells need different bounds.
    *
    * @param cellMin positive lower bound and nominal modeled cell delay
    * @param cellMax upper bound for every control cell and latch
    * @param dataMax complete transform/glue-path delay allowance before storage
    * @return policy with request guard `dataMax + cellMin` and output guard
    *   `3 * cellMax + cellMin`, avoiding equality-dependent event ordering
    */
  def simulation(cellMin: ModelTime = ModelTime.ps(1000), cellMax: ModelTime = ModelTime.ps(10000),
      dataMax: ModelTime = ModelTime.ps(10000)): Digital = {
    require(cellMin.fs > 0 && cellMin.fs <= cellMax.fs, "invalid simulation cell bounds")
    val cells = DelayBounds(cellMin, cellMax, cellMin)
    Digital(dataMax + cellMin, DelayBounds.fixed(dataMax), ControlDelays.uniform(cells), cells,
      cellMax + cellMax + cellMax + cellMin)
  }
  /** Deliberately named zero-delay mode for the historical functional contract corpus. */
  case object FunctionalOnly extends BundledTiming {
    val matchedDelay = ModelTime(0)
    val dataDelay = DelayBounds.fixed(ModelTime(0))
    val controls = ControlDelays.uniform(dataDelay)
    val latchDelay = dataDelay
    val outputDelay = ModelTime(0)
    val mode = "functional-only"
  }

  /** The data delay models the whole pure transform path, before storage.
    * Conservative strict margins avoid equality/delta-order assumptions:
    * request admission follows valid data; output offer follows acceptance and q propagation.
    */
  final case class Digital(matchedDelay: ModelTime, dataDelay: DelayBounds,
                           controls: ControlDelays, latchDelay: DelayBounds,
                           outputDelay: ModelTime) extends BundledTiming {
    require((controls.values :+ latchDelay).forall(_.min.fs > 0), "digital cell/latch lower bounds must be positive")
    require(matchedDelay.fs > dataDelay.max.fs, "matched delay must exceed maximum modeled data delay")
    val minimumOutputGuard: ModelTime = controls.worst + controls.worst + latchDelay.max
    require(outputDelay.fs > minimumOutputGuard.fs,
      "output delay must exceed twice the largest control bound plus maximum latch propagation")
    val mode = "digital-model"
  }
}
