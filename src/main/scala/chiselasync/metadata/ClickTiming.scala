// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Independent propagation bounds for the native Click controller cells.
  * Each [[DelayBounds]] records minimum, maximum and nominal simulation values.
  * Standard Click shares `inputPhase` between its two comparators; `outputPhase`
  * remains part of the common conservative policy but adds no physical cell.
  *
  * @param inputCompare XOR comparing delayed input request with input phase
  * @param outputCompare XOR comparing output phase with downstream acknowledgement
  * @param fire AND generating the local capture pulse (and the seeded start barrier)
  * @param inputPhase trigger-to-Q bounds of the input phase register
  * @param outputPhase trigger-to-Q bounds of the phase-decoupled output register
  */
final case class ClickControlDelays(inputCompare: DelayBounds, outputCompare: DelayBounds,
    fire: DelayBounds, inputPhase: DelayBounds, outputPhase: DelayBounds)

/** Timing contract for a native, edge-triggered Click stage.
  * Guards use worst-case bounds, including the declared local pulse distribution
  * skew. These are digital assumptions, not characterized technology values.
  * The data budget replaces the complete mapped transform path; it is not an
  * additional physical buffer to insert after that path.
  *
  * Start a digital experiment with [[ClickTiming.Simulation]]. Customize its
  * fields with `copy`; every copy rechecks the strict guard inequalities. Timing
  * equality is rejected. [[ModelTime]] values use femtoseconds; `ModelTime.ps`
  * converts picoseconds exactly. These bounds do not establish physical timing closure.
  *
  * @param controls independently bounded XOR, AND and phase-register delays
  * @param payload local-trigger-to-Q bounds of the edge-triggered data register
  * @param data bounds for the entire combinational input-to-register data path
  * @param requestDelay input request guard, strictly larger than `data.max + setup`
  * @param acknowledgeDelay guard before upstream acknowledgement and payload reuse
  * @param outputDelay guard before advertising output data or allowing fast downstream acknowledgement
  * @param setup required data stability before the payload trigger edge
  * @param hold required data stability after the payload trigger edge
  * @param pulseHigh strict minimum high width at every register trigger pin
  * @param pulseLow strict minimum low width at every register trigger pin
  * @param clockSkew maximum added delay from the firing gate to any register trigger pin
  */
final case class ClickTiming(controls: ClickControlDelays, payload: DelayBounds, data: DelayBounds,
    requestDelay: ModelTime, acknowledgeDelay: ModelTime, outputDelay: ModelTime,
    setup: ModelTime, hold: ModelTime, pulseHigh: ModelTime, pulseLow: ModelTime,
    clockSkew: ModelTime) {
  /** Semantic primitive identifiers and their bounds, used by export and delay campaigns. */
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
    ClickTiming(
      controls = ClickControlDelays(cell, cell, cell, cell, cell),
      payload = cell,
      data = DelayBounds.fixed(ModelTime.ps(10000)),
      requestDelay = ModelTime.ps(11000),
      acknowledgeDelay = ModelTime.ps(32000),
      outputDelay = ModelTime.ps(32000),
      setup = ModelTime.ps(100),
      hold = ModelTime.ps(100),
      pulseHigh = ModelTime.ps(100),
      pulseLow = ModelTime.ps(100),
      clockSkew = ModelTime.ps(100))
  }
}
