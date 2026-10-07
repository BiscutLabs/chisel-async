// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Independent bounds for the two comparators, firing gate and phase registers. */
final case class ClickControlDelays(inputCompare: DelayBounds, outputCompare: DelayBounds,
    fire: DelayBounds, inputPhase: DelayBounds, outputPhase: DelayBounds)

/** Timing contract for a native, edge-triggered Click stage.
  * Guards use worst-case bounds, including the declared local pulse distribution
  * skew. These are digital assumptions, not characterized technology values.
  * The data budget replaces the complete mapped transform path; it is not an
  * additional physical buffer to insert after that path.
  */
final case class ClickTiming(controls: ClickControlDelays, payload: DelayBounds, data: DelayBounds,
    requestDelay: ModelTime, acknowledgeDelay: ModelTime, outputDelay: ModelTime,
    setup: ModelTime, hold: ModelTime, pulseHigh: ModelTime, pulseLow: ModelTime,
    clockSkew: ModelTime) {
  val cells: Map[String, DelayBounds] = Map("input_compare" -> controls.inputCompare,
    "output_compare" -> controls.outputCompare, "fire" -> controls.fire,
    "input_phase" -> controls.inputPhase, "output_phase" -> controls.outputPhase,
    "payload" -> payload, "data_delay" -> data)
  require(cells.filterNot(_._1 == "data_delay").values.forall(_.min.fs > 0), "CLICK_POSITIVE_CELL_BOUNDS")
  require(pulseHigh.fs > 0 && pulseLow.fs > 0, "CLICK_POSITIVE_PULSE_REQUIREMENTS")
  require(BigInt(requestDelay.fs) > BigInt(data.max.fs) + setup.fs, "CLICK_DATA_GUARD")
  // Standard Click feeds both comparators from the input phase register. Take
  // independent minima so this shared policy also covers that cross-pairing.
  private val shortestFeedback = BigInt(math.min(controls.inputPhase.min.fs, controls.outputPhase.min.fs)) +
    math.min(controls.inputCompare.min.fs, controls.outputCompare.min.fs) + controls.fire.min.fs
  require(shortestFeedback > BigInt(pulseHigh.fs) + clockSkew.fs, "CLICK_HIGH_PULSE_BOUND")
  private val settled = BigInt(clockSkew.fs) + math.max(controls.inputPhase.max.fs, controls.outputPhase.max.fs) +
    math.max(controls.inputCompare.max.fs, controls.outputCompare.max.fs) + controls.fire.max.fs
  require(BigInt(acknowledgeDelay.fs) > settled + pulseLow.fs &&
    BigInt(acknowledgeDelay.fs) > BigInt(clockSkew.fs) + hold.fs, "CLICK_ACK_GUARD")
  require(BigInt(outputDelay.fs) > settled + pulseLow.fs &&
    BigInt(outputDelay.fs) > BigInt(clockSkew.fs) + payload.max.fs, "CLICK_OUTPUT_GUARD")
}

object ClickTiming {
  /** Conservative digital experiment: independent 1..10 ns cells, 10 ns data,
    * 100 ps setup/hold/pulse requirements and 100 ps local clock skew allowance.
    * Physical speed and energy comparisons require a characterized mapping.
    */
  val Simulation: ClickTiming = {
    val cell = DelayBounds(ModelTime.ps(1000), ModelTime.ps(10000), ModelTime.ps(1000))
    ClickTiming(ClickControlDelays(cell,cell,cell,cell,cell),cell,DelayBounds.fixed(ModelTime.ps(10000)),
      ModelTime.ps(11000),ModelTime.ps(32000),ModelTime.ps(32000),
      ModelTime.ps(100),ModelTime.ps(100),ModelTime.ps(100),ModelTime.ps(100),ModelTime.ps(100))
  }
}
