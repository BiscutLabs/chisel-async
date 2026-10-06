// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

/** Explicit digital timing policy. None of these values constitutes technology timing closure. */
sealed trait BundledTiming {
  def matchedDelay: ModelTime
  def dataDelay: ModelTime
  def cellDelay: ModelTime
  def latchDelay: ModelTime
  def outputDelay: ModelTime
  def mode: String
}
object BundledTiming {
  /** Deliberately named zero-delay mode for the historical functional contract corpus. */
  case object FunctionalOnly extends BundledTiming {
    val matchedDelay = ModelTime(0)
    val dataDelay = ModelTime(0)
    val cellDelay = ModelTime(0)
    val latchDelay = ModelTime(0)
    val outputDelay = ModelTime(0)
    val mode = "functional-only"
  }

  /** The data delay models the whole pure transform path, before storage.
    * Conservative strict margins avoid equality/delta-order assumptions:
    * request admission follows valid data; output offer follows acceptance and q propagation.
    */
  final case class Digital(matchedDelay: ModelTime, dataDelay: ModelTime,
                           cellDelay: ModelTime, latchDelay: ModelTime,
                           outputDelay: ModelTime) extends BundledTiming {
    require(cellDelay.fs > 0 && latchDelay.fs > 0, "digital cell/latch delays must be positive")
    require(matchedDelay.fs > dataDelay.fs, "matched delay must exceed modeled data delay")
    require(outputDelay.fs > (cellDelay + cellDelay + latchDelay).fs,
      "output delay must exceed two control-cell delays plus latch propagation")
    val mode = "digital-model"
  }
}
