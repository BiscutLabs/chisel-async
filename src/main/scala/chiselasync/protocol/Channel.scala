// SPDX-License-Identifier: Apache-2.0
package chiselasync.protocol

import chisel3._
import chisel3.util.{Decoupled, DecoupledIO}
import chiselasync.core.ResetDomain

/** Logical ordered token stream, independent of wires and transfer timing.
  * No storage, clock or implicit converter is created by this descriptor.
  * Capacity, acknowledgement/commit events and electrical hold rules belong to the implementation.
  */
final class Channel[T <: Data](val payload: T, val domain: ResetDomain) {
  Payload.validateType(payload)
  val tokenContract: String = "ordered-lossless-reset-abort-v1"
  def bundled: FourPhase[T] = new FourPhase(payload.cloneType, Some(domain))
  def dualRail: DualRail[T] = new DualRail(payload.cloneType, domain)
  def decoupled: DecoupledIO[T] = Decoupled(payload.cloneType)
  def requireCompatible[U <: Data](other: Channel[U]): Unit = {
    Payload.requireSame(payload, other.payload)
    require(domain eq other.domain, "logical channel reset domains differ")
  }
}

/** Return-to-zero 1-of-2 encoding. Each bit pair is 00 spacer, 10 zero, 01 one.
  * 11 is illegal. Rails rise monotonically to data and fall monotonically to spacer.
  */
class DualRail[T <: Data](gen: T, val domain: ResetDomain) extends Bundle {
  Payload.validateType(gen)
  val zero = Output(gen.cloneType)
  val one = Output(gen.cloneType)
  val ack = Input(Bool())
}
object DualRail {
  def connect[T <: Data](consumer: DualRail[T], producer: DualRail[T]): Unit = {
    Payload.requireSame(consumer.one, producer.one)
    require(consumer.domain eq producer.domain, "dual-rail reset domains differ")
    consumer :<>= producer
  }
}
