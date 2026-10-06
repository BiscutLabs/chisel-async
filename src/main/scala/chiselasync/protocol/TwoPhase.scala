// SPDX-License-Identifier: Apache-2.0
package chiselasync.protocol

import chisel3._
import chiselasync.core.ResetDomain

/** Transition-signalled bundled data. Reset is 00; req != ack is one pending token.
  * Both acknowledgement polarities complete a transfer. Hold data until parity matches.
  */
class TwoPhase[T <: Data](gen: T, val domain: ResetDomain) extends Bundle {
  Payload.validateType(gen)
  private[chiselasync] def payloadType: T = gen.cloneType
  val req = Output(Bool())
  val bits = Output(gen.cloneType)
  val ack = Input(Bool())
}
object TwoPhase {
  def connect[T <: Data](consumer: TwoPhase[T], producer: TwoPhase[T]): Unit = {
    Payload.requireSame(consumer.bits, producer.bits)
    require(consumer.domain eq producer.domain, "two-phase reset domains differ")
    consumer :<>= producer
  }
}
