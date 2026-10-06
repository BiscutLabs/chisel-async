// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chisel3._
import chisel3.reflect.DataMirror
import chiselasync.core.AsyncModule
import chiselasync.protocol.FourPhase
import scala.collection.mutable.ArrayBuffer

/** Per-module, explicit registry. No mutable singleton or ambient elaboration state. */
final class DesignContract private[chiselasync] (owner: AsyncModule) {
  private val ids = scala.collection.mutable.Set.empty[String]
  private val endpoints = ArrayBuffer.empty[(String, Data, UInt)]
  private val channels = ArrayBuffer.empty[() => ujson.Value]
  private val primitives = ArrayBuffer.empty[() => ujson.Value]
  private val children = ArrayBuffer.empty[(String, AsyncModule)]
  private val obligations = ArrayBuffer.empty[ujson.Value]
  private var storageCapacity: Option[Int] = None

  def capacity(tokens: Int): Unit = {
    require(tokens > 0 && storageCapacity.isEmpty, "capacity must be positive and declared once")
    storageCapacity = Some(tokens)
  }

  private def claim(id: String): Unit = {
    require(id.matches("[A-Za-z][A-Za-z0-9_]*"), s"invalid semantic ID: $id")
    require(ids.add(id), s"duplicate semantic ID: $id")
  }

  /** A ground output is the supported compiler anchor; export validation resolves it in RTL. */
  def endpoint(id: String, signal: Data): String = {
    claim(id)
    require(signal.isWidthKnown && signal.getWidth > 0, s"unknown endpoint width: $id")
    val anchor = IO(Output(UInt(signal.getWidth.W))).suggestName(s"ca_$id")
    anchor := signal.asUInt
    dontTouch(anchor)
    endpoints += ((id, signal, anchor))
    id
  }

  def channel[T <: Data](id: String, port: FourPhase[T], role: String): Unit = {
    claim(id)
    require(port.domain.contains(owner.resetDomain), s"unbound reset domain: $id")
    require(Set("input", "output").contains(role), "invalid channel role")
    val req = endpoint(s"${id}_request", port.req)
    val bits = endpoint(s"${id}_data", port.bits)
    val ack = endpoint(s"${id}_acknowledge", port.ack)
    channels += (() => ujson.Obj("id" -> id, "protocol" -> "four-phase-bundled-v1", "role" -> role,
      "request" -> req, "data" -> bits, "acknowledge" -> ack,
      "reset_domain" -> owner.resetDomain.id, "layout" -> layout(port.bits),
      "phases" -> ujson.Arr("00", "10", "11", "01", "00"),
      "environment" -> "binary inputs; coordinated reset; data held through return to idle"))
  }

  def primitive(id: String, instance: ExtModule, parameters: Map[String, BigInt],
                resetEndpoint: String, effects: String): Unit = {
    claim(id)
    require(endpoints.exists(_._1 == resetEndpoint), s"missing primitive reset endpoint: $resetEndpoint")
    instance.suggestName(s"ca_primitive_$id")
    primitives += (() => ujson.Obj("id" -> id, "rtl_path" -> instance.pathName,
      "model" -> instance.desiredName, "view" -> "behavioral", "version" -> 1,
      "resource" -> s"chiselasync/sv/${instance.desiredName}.sv",
      "parameters" -> ujson.Obj.from(parameters.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Str(v.toString) }),
      "reset" -> resetEndpoint, "reset_domain" -> owner.resetDomain.id, "effects" -> effects,
      "ports" -> ujson.Arr.from(DataMirror.modulePorts(instance).map { case (name, data) =>
        ujson.Obj("name" -> name, "width" -> data.getWidth,
          "direction" -> DataMirror.directionOf(data).toString.toLowerCase)
      })))
  }

  def child(id: String, module: AsyncModule): Unit = {
    claim(id)
    require(module.resetDomain eq owner.resetDomain, "child reset domains differ")
    module.suggestName(s"ca_child_$id")
    children += id -> module
  }

  def setupHold(id: String, launch: String, transaction: String, dataValid: String,
                capture: String, captured: String, setup: ModelTime, hold: ModelTime): Unit = {
    claim(id)
    Seq(launch, transaction, dataValid, capture, captured).foreach { ref =>
      require(endpoints.exists(_._1 == ref), s"missing timing endpoint: $ref")
    }
    obligations += ujson.Obj("id" -> id, "kind" -> "bundled-setup-hold-v1", "launch" -> launch,
      "transaction" -> transaction, "data_valid" -> dataValid, "capture" -> capture,
      "captured" -> captured, "setup_fs" -> setup.fs.toString, "hold_fs" -> hold.fs.toString,
      "mode" -> "digital-model", "provenance" -> "explicit fixture contract",
      "pulse_policy" -> "one outstanding launch; identity travels with data; capture on rising edge")
  }

  def longHoldTiming(id: String, policy: BundledTiming, request: String, inputData: String,
                     latchData: String, latchClosed: String, acknowledge: String,
                     outputRequest: String, outputData: String): Unit = {
    claim(id)
    Seq(request, inputData, latchData, latchClosed, acknowledge, outputRequest, outputData).foreach { ref =>
      require(endpoints.exists(_._1 == ref), s"missing timing endpoint: $ref")
    }
    obligations += ujson.Obj("id" -> id, "kind" -> "long-hold-bundling-v1", "mode" -> policy.mode,
      "request" -> request, "input_data" -> inputData, "latch_data" -> latchData,
      "latch_closed" -> latchClosed, "acknowledge" -> acknowledge,
      "output_request" -> outputRequest, "output_data" -> outputData,
      "matched_delay_fs" -> policy.matchedDelay.fs.toString, "data_delay_fs" -> policy.dataDelay.fs.toString,
      "cell_delay_fs" -> policy.cellDelay.fs.toString, "latch_delay_fs" -> policy.latchDelay.fs.toString,
      "output_delay_fs" -> policy.outputDelay.fs.toString,
      "provenance" -> "explicit model policy; not technology timing closure",
      "assumptions" -> "atomic asymmetric cells including input bubbles; ideal forks; zero latch aperture; coordinated quiescent reset")
  }

  private def layout(data: Data): ujson.Value = {
    var offset = 0
    val leaves = ArrayBuffer.empty[ujson.Value]
    def visit(value: Data, path: String): Unit = value match {
      // Chisel's Record.elements is in packing order, least-significant field first.
      case record: Record => record.elements.foreach { case (name, field) => visit(field, s"$path.$name") }
      case vector: Vec[_] => vector.zipWithIndex.foreach { case (field, index) => visit(field, s"$path[$index]") }
      case _ =>
        leaves += ujson.Obj("field" -> path, "lsb" -> offset, "width" -> value.getWidth,
          "signed" -> value.isInstanceOf[SInt], "source" -> value.toTarget.serialize)
        offset += value.getWidth
    }
    visit(data, "bits")
    ujson.Arr.from(leaves)
  }

  private[chiselasync] def json: ujson.Value = ujson.Obj(
    "rtl_path" -> owner.pathName, "module" -> owner.name, "reset_domain" -> owner.resetDomain.id,
    "capacity" -> storageCapacity.map(n => ujson.Num(n)).getOrElse(ujson.Null),
    "endpoints" -> ujson.Arr.from(endpoints.map { case (id, source, anchor) =>
      ujson.Obj("id" -> id, "rtl_path" -> anchor.pathName, "width" -> anchor.getWidth,
        "source" -> source.toTarget.serialize)
    }), "channels" -> ujson.Arr.from(channels.map(_())),
    "primitives" -> ujson.Arr.from(primitives.map(_())), "timing" -> ujson.Arr.from(obligations),
    "children" -> ujson.Arr.from(children.map { case (id, module) =>
      ujson.Obj("id" -> id, "contract" -> module.contract.json)
    }))
}
