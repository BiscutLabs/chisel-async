// SPDX-License-Identifier: Apache-2.0
package chiselasync.protocol

import chisel3._
import chisel3.reflect.DataMirror

/** Validation at the typed channel boundary. No implicit resizing or field coercion. */
private[chiselasync] object Payload {
  def validateType(data: Data): Unit = {
    def visit(value: Data, path: String): Unit = {
      require(DataMirror.specifiedDirectionOf(value) == SpecifiedDirection.Unspecified,
        s"payload $path must not contain explicit directions")
      require(!DataMirror.hasProbeTypeModifier(value), s"payload $path cannot contain probes")
      value match {
        case _: UInt | _: SInt =>
          require(value.isWidthKnown && value.getWidth > 0, s"payload $path requires a known positive width")
        case vector: Vec[_] =>
          require(vector.length > 0, s"payload $path cannot be an empty Vec")
          vector.zipWithIndex.foreach { case (element, index) => visit(element, s"$path[$index]") }
        case record: Bundle =>
          require(record.elements.nonEmpty, s"payload $path cannot be an empty Bundle")
          record.elements.foreach { case (name, element) => visit(element, s"$path.$name") }
        case _ => throw new IllegalArgumentException(s"unsupported payload at $path: ${value.getClass.getSimpleName}")
      }
    }
    visit(data, "bits")
  }

  def requireSame(left: Data, right: Data): Unit = {
    require(DataMirror.checkTypeEquivalence(left, right),
      "channel payloads must have identical field types, widths and shape; use an explicit adapter")
  }
}
