// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.clocked._
import circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite

class BoundarySpec extends AnyFunSuite {
  test("memory ports preserve byte-address and byte-mask widths across both encodings") {
    for (bits <- Seq(8, 16, 32, 64)) {
      val text = ChiselStage.emitCHIRRTL(new AsyncMemoryPort(MemoryShape(24, bits)))
      assert(text.contains(s"data : UInt<$bits>") && text.contains(s"mask : UInt<${bits / 8}>"))
      assert(text.contains("backendReset : AsyncReset") && text.contains("clock : Clock"))
    }
  }
  test("memory shapes reject fractional bytes and non-power-of-two words") {
    for (bits <- Seq(0, 7, 12, 24)) intercept[IllegalArgumentException] { MemoryShape(24, bits) }
    intercept[IllegalArgumentException] { MemoryShape(2, 32) }
  }
  test("application boundaries reject one-stage synchronizers and empty event banks") {
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new AsyncMemoryPort(MemoryShape(8, 16), 1)) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new PendingEventBridge(4, 1)) }
    intercept[IllegalArgumentException] { ChiselStage.emitCHIRRTL(new PendingEventBridge(0)) }
  }
}
