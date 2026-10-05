// SPDX-License-Identifier: Apache-2.0
package chiselasync.protocol

import chisel3._
import chiselasync.core.ResetDomain

/** Producer-oriented bundled data. Hold bits from before req rises until req/ack return to zero. */
class FourPhase[T <: Data](gen: T, val domain: Option[ResetDomain] = None) extends Bundle {
  Payload.validateType(gen)
  val req = Output(Bool())
  val bits = Output(gen)
  val ack = Input(Bool())
}

object FourPhase {
  /** Both endpoints must share a coordinated reset domain. Independent reset needs a bridge. */
  def connect[T <: Data](consumer: FourPhase[T], producer: FourPhase[T]): Unit = {
    Payload.requireSame(consumer.bits, producer.bits)
    require(consumer.domain == producer.domain,
      "channel reset domains differ; share a ResetDomain object or use an explicit restart bridge")
    consumer :<>= producer
  }
}
