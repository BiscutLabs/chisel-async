// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.experimental.UnsafeFourPhaseBuffer
import chiselasync.metadata.ExportDesign
import java.nio.file.Paths

// Eight payload bits plus a 32-bit transaction identity, including equal payloads.
class ControllerComparisonExample extends UnsafeFourPhaseBuffer(UInt(40.W))

object EmitControllerComparison {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: EmitControllerComparison <output-directory>")
    ExportDesign.emit(new ControllerComparisonExample, Paths.get(args(0)), ExportDesign.Debug)
  }
}
