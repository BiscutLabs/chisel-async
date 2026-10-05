// SPDX-License-Identifier: Apache-2.0
package chiselasync.core

/** Share this object only between endpoints with coordinated reset. */
final class ResetDomain(val id: String) {
  require(id.matches("[A-Za-z][A-Za-z0-9_-]*"), "invalid reset domain ID")
}
