// SPDX-License-Identifier: Apache-2.0
package chiselasync.examples

import chisel3._
import chiselasync.clocked.{ClickCaptureReceipt, FourPhaseCaptureReceipt}
import chiselasync.metadata.ExportDesign
import java.nio.file.Paths

/** Small exports for the independent Icarus retained-payload boundary campaign. */
object EmitCaptureReceipts {
  def main(args: Array[String]): Unit = {
    require(args.length == 1)
    for (click <- Seq(false, true); stages <- Seq(2, 3);
         settling <- Seq(0, 1, 3); mask <- Seq(false, true)) {
      val width = Seq(1, 8, 337)(Seq(0, 1, 3).indexOf(settling))
      val id = s"capture_${if (click) "click" else "bd"}_${stages}_${settling}_${if (mask) 1 else 0}"
      if (click) ExportDesign.emit(new ClickCaptureReceipt(UInt(width.W), stages, settling, mask), Paths.get(args(0), id))
      else ExportDesign.emit(new FourPhaseCaptureReceipt(UInt(width.W), stages, settling, mask), Paths.get(args(0), id))
    }
  }
}
