// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

/** Storage selection for transient four-phase stage payloads. Control always
  * resets. Resetless payload is unknown/stale until a valid offer and must not
  * be used for initialized state or unqualified outputs/side effects.
  */
sealed trait PayloadStorage
object PayloadStorage {
  case object Resettable extends PayloadStorage
  case object Resetless extends PayloadStorage
}
