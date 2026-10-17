// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Simulation treatment of the whole combinational payload transform. */
sealed trait DataAllowance
object DataAllowance {
  /** Existing reset-masked ControlGate model; retained for source compatibility. */
  case object Resettable extends DataAllowance
  /** Reset-free, unmasked inertial model; physical implementation is a wire.
    * Invalid data may change or be unknown. Capture and side effects must be
    * qualified by the owning handshake, with independent setup/hold checks.
    */
  case object Passive extends DataAllowance
}
