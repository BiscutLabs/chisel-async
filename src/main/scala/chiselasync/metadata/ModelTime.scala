// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Exact model time, not a statement of physical accuracy. */
final case class ModelTime(fs: Long) {
  require(fs >= 0, "model time must be nonnegative")
  def +(other: ModelTime): ModelTime = ModelTime(Math.addExact(fs, other.fs))
  def ticks(precision: ModelTime): Long = {
    require(precision.fs > 0 && fs % precision.fs == 0, "time is not exactly representable at simulator precision")
    fs / precision.fs
  }
}
object ModelTime {
  def ps(value: Long): ModelTime = ModelTime(Math.multiplyExact(value, 1000L))
}

sealed abstract class DelayPolicy(val name: String, val code: Int)
object DelayPolicy {
  case object Transport extends DelayPolicy("transport", 0)
  case object Inertial extends DelayPolicy("inertial-due-before-input", 1)
}
