// SPDX-License-Identifier: Apache-2.0
package chiselasync.metadata

import chisel3._
import chisel3.reflect.DataMirror
import chisel3.probe.{Probe, ProbeValue, define}
import chisel3.experimental.noPrefix
import chiselasync.core.AsyncModule
import chiselasync.protocol.{Channel, DualRail, FourPhase, Payload, TwoPhase}
import chisel3.util.DecoupledIO
import scala.collection.mutable.ArrayBuffer

/** Per-module, explicit registry. No mutable singleton or ambient elaboration state. */
final class DesignContract private[chiselasync] (owner: AsyncModule) {
  private val ids = scala.collection.mutable.Set.empty[String]
  private val endpoints = ArrayBuffer.empty[(String, Data, UInt)]
  private val observations = ArrayBuffer.empty[(Vector[String], UInt)]

  private def probeName(path: Vector[String]): String =
    "ca_p_" + path.map(id => s"${id.length}_$id").mkString("_")
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

  /** Read-only references lower to the compiler's probe ABI, never hardware ports. */
  def endpoint(id: String, signal: Data): String = noPrefix {
    claim(id)
    require(signal.isWidthKnown && signal.getWidth > 0, s"unknown endpoint width: $id")
    val anchor = IO(Output(Probe(UInt(signal.getWidth.W)))).suggestName(probeName(Vector(id)))
    val packed = Wire(UInt(signal.getWidth.W))
    packed := signal.asUInt
    define(anchor, ProbeValue(packed))
    endpoints += ((id, signal, anchor))
    observations += Vector(id) -> anchor
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
      "token_contract" -> "ordered-lossless-reset-abort-v1",
      "environment" -> "binary inputs; coordinated reset; data held through return to idle"))
  }

  def twoPhaseChannel[T <: Data](id: String, port: TwoPhase[T], role: String): Unit = {
    claim(id)
    require(port.domain eq owner.resetDomain, s"unbound reset domain: $id")
    require(Set("input", "output").contains(role), "invalid channel role")
    val req = endpoint(s"${id}_request", port.req)
    val bits = endpoint(s"${id}_data", port.bits)
    val ack = endpoint(s"${id}_acknowledge", port.ack)
    channels += (() => ujson.Obj("id" -> id, "protocol" -> "two-phase-bundled-v1", "role" -> role,
      "request" -> req, "data" -> bits, "acknowledge" -> ack,
      "reset_domain" -> owner.resetDomain.id, "layout" -> layout(port.bits),
      "phases" -> ujson.Arr("00", "10", "11", "01", "00"),
      "token_contract" -> "ordered-lossless-reset-abort-v1",
      "environment" -> "binary inputs; coordinated reset to 00; every ack edge delivers; data held while req != ack"))
  }

  def dualRailChannel[T <: Data](id: String, port: DualRail[T], role: String): Unit = {
    claim(id)
    require(port.domain eq owner.resetDomain, s"unbound reset domain: $id")
    require(Set("input", "output").contains(role), "invalid channel role")
    val zero = endpoint(s"${id}_zero", port.zero)
    val one = endpoint(s"${id}_one", port.one)
    val ack = endpoint(s"${id}_acknowledge", port.ack)
    channels += (() => ujson.Obj("id" -> id, "protocol" -> "dual-rail-rtz-v1", "role" -> role,
      "zero" -> zero, "one" -> one, "acknowledge" -> ack,
      "reset_domain" -> owner.resetDomain.id, "layout" -> layout(port.one),
      "phases" -> ujson.Arr("spacer", "data", "acknowledged", "spacer", "idle"),
      "token_contract" -> "ordered-lossless-reset-abort-v1",
      "environment" -> "monotonic 1-of-2 rails; all-spacer return; coordinated reset; ideal forks in digital probe"))
  }

  def clockedChannel[T <: Data](id: String, port: DecoupledIO[T], clock: Clock,
                                logical: Channel[T], role: String): Unit = {
    claim(id)
    require(logical.domain eq owner.resetDomain, s"unbound reset domain: $id")
    Payload.requireSame(port.bits, logical.payload)
    require(Set("input", "output").contains(role), "invalid channel role")
    val valid = endpoint(s"${id}_valid", port.valid)
    val bits = endpoint(s"${id}_data", port.bits)
    val ready = endpoint(s"${id}_ready", port.ready)
    val edge = endpoint(s"${id}_clock", clock)
    channels += (() => ujson.Obj("id" -> id, "protocol" -> "decoupled-v1", "role" -> role,
      "valid" -> valid, "data" -> bits, "ready" -> ready, "clock" -> edge,
      "reset_domain" -> owner.resetDomain.id, "layout" -> layout(port.bits),
      "phases" -> ujson.Arr("rising-edge-fire"), "token_contract" -> logical.tokenContract,
      "environment" -> "transfer only at rising clock with ready and valid; no input irrevocability assumed; coordinated reset"))
  }

  def primitive(id: String, instance: ExtModule, parameters: Map[String, BigInt],
                resetEndpoint: String, effects: String, view: String = "behavioral"): Unit = {
    claim(id)
    require(Set("behavioral", "constraint-marker").contains(view), "invalid primitive view")
    require(endpoints.exists(_._1 == resetEndpoint), s"missing primitive reset endpoint: $resetEndpoint")
    instance.suggestName(s"ca_primitive_$id")
    primitives += (() => ujson.Obj("id" -> id, "rtl_path" -> instance.pathName,
      "model" -> instance.desiredName, "view" -> view, "version" -> 1,
      "resource" -> s"chiselasync/sv/${instance.desiredName}.sv",
      "parameters" -> ujson.Obj.from(parameters.toSeq.sortBy(_._1).map { case (k, v) => k -> ujson.Str(v.toString) }),
      "reset" -> resetEndpoint, "reset_domain" -> owner.resetDomain.id, "effects" -> effects,
      "ports" -> ujson.Arr.from(DataMirror.modulePorts(instance).map { case (name, data) =>
        ujson.Obj("name" -> name, "width" -> data.getWidth,
          "direction" -> DataMirror.directionOf(data).toString.toLowerCase)
      })))
  }

  def child(id: String, module: AsyncModule): Unit = noPrefix {
    claim(id)
    require(module.resetDomain eq owner.resetDomain, "child reset domains differ")
    module.suggestName(s"ca_child_$id")
    children += id -> module
    // Forward references, not dataflow. The top-level ref_<top>.sv ABI contains
    // every semantic endpoint even when identical child definitions deduplicate.
    module.contract.observations.foreach { case (path, probe) =>
      val key = id +: path
      val forwarded = IO(Output(Probe(UInt(probe.getWidth.W)))).suggestName(probeName(key))
      define(forwarded, probe)
      observations += key -> forwarded
    }
  }

  def setupHold(id: String, launch: String, transaction: String, dataValid: String,
                capture: String, captured: String, setup: ModelTime, hold: ModelTime): Unit = {
    claim(id)
    Seq(launch, transaction, dataValid, capture, captured).foreach { ref =>
      require(endpoints.exists(_._1 == ref), s"missing timing endpoint: $ref")
    }
    val refs = Seq(launch, transaction, dataValid, capture, captured)
    val marker = timingMarker(id, refs, Map("KIND" -> BigInt(1), "SETUP_FS" -> BigInt(setup.fs), "HOLD_FS" -> BigInt(hold.fs)))
    obligations += ujson.Obj("id" -> id, "kind" -> "bundled-setup-hold-v1", "marker" -> marker, "launch" -> launch,
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
    def bounds(value: DelayBounds): ujson.Value = ujson.Obj("min_fs" -> value.min.fs.toString,
      "max_fs" -> value.max.fs.toString, "model_fs" -> value.model.fs.toString)
    val limits = Seq("A" -> policy.controls.a, "B" -> policy.controls.b,
      "ACKNOWLEDGE" -> policy.controls.acknowledge, "LONG_HOLD" -> policy.controls.longHold,
      "DATA" -> policy.dataDelay, "LATCH" -> policy.latchDelay).flatMap { case (role, value) =>
      Seq(s"${role}_MIN_FS" -> BigInt(value.min.fs), s"${role}_MAX_FS" -> BigInt(value.max.fs),
        s"${role}_MODEL_FS" -> BigInt(value.model.fs))
    }.toMap ++ Map("KIND" -> BigInt(2), "MATCHED_FS" -> BigInt(policy.matchedDelay.fs), "OUTPUT_FS" -> BigInt(policy.outputDelay.fs))
    val marker = timingMarker(id, Seq(request, inputData, latchData, latchClosed, acknowledge, outputRequest, outputData), limits)
    obligations += ujson.Obj("id" -> id, "kind" -> "long-hold-bundling-v2", "marker" -> marker, "mode" -> policy.mode,
      "request" -> request, "input_data" -> inputData, "latch_data" -> latchData,
      "latch_closed" -> latchClosed, "acknowledge" -> acknowledge,
      "output_request" -> outputRequest, "output_data" -> outputData,
      "matched_delay_fs" -> policy.matchedDelay.fs.toString, "data_delay" -> bounds(policy.dataDelay),
      "control_delays" -> ujson.Obj("a" -> bounds(policy.controls.a), "b" -> bounds(policy.controls.b),
        "acknowledge" -> bounds(policy.controls.acknowledge), "long_hold" -> bounds(policy.controls.longHold)),
      "latch_delay" -> bounds(policy.latchDelay),
      "output_delay_fs" -> policy.outputDelay.fs.toString,
      "provenance" -> "explicit model policy; not technology timing closure",
      "assumptions" -> "atomic input bubbles; Aout+ reaches long_hold.b before A- reaches long_hold.a; ideal model wires; zero latch aperture; coordinated reset")
  }

  /** A whole-path budget, including ideal Chisel glue. The delay primitive models
    * this budget once; its delay is not an additional allowance for physical glue.
    * delayOwner is a relative sequence of registered child IDs (empty = this node).
    */
  def dataPathTiming(id: String, source: String, sink: String, policy: BundledTiming,
                     logic: String, delayOwner: Seq[String] = Seq.empty,
                     delayCell: String = "data_delay"): Unit = {
    claim(id)
    val bounds = policy.dataDelay
    val marker = timingMarker(id, Seq(source, sink), Map("KIND" -> BigInt(3),
      "DATA_MIN_FS" -> BigInt(bounds.min.fs), "DATA_MAX_FS" -> BigInt(bounds.max.fs),
      "DATA_MODEL_FS" -> BigInt(bounds.model.fs)))
    obligations += ujson.Obj("id" -> id, "kind" -> "bundled-data-path-v1", "marker" -> marker,
      "source" -> source, "sink" -> sink, "logic" -> logic, "logic_model_fs" -> "0",
      "budget" -> ujson.Obj("min_fs" -> bounds.min.fs.toString, "max_fs" -> bounds.max.fs.toString,
        "model_fs" -> bounds.model.fs.toString),
      "delay_owner" -> ujson.Arr.from(delayOwner), "delay_cell" -> delayCell,
      "accounting" -> "included-in-delay-cell; replace-model-with-mapped-path; not-additive")
  }

  def longHoldFork(id: String, aout: String, stateA: String, policy: BundledTiming): Unit = {
    claim(id)
    val marker = timingMarker(id, Seq(aout, stateA), Map("KIND" -> BigInt(4),
      "A_MIN_FS" -> BigInt(policy.controls.a.min.fs)))
    obligations += ujson.Obj("id" -> id, "kind" -> "long-hold-fork-v1", "marker" -> marker,
      "aout" -> aout, "state_a" -> stateA, "early_pin" -> "long_hold.b",
      "late_pin" -> "long_hold.a", "relation" -> "Aout+ strictly before A- at OR inputs",
      "model_wire_skew_fs" -> "0", "a_min_fs" -> policy.controls.a.min.fs.toString)
  }

  def phaseTiming(id: String, direction: String, policy: PhaseTiming): Unit = {
    require(Set("two-to-four", "four-to-two").contains(direction), "invalid phase converter direction")
    claim(id)
    val refs = Seq("in_request", "in_acknowledge", "out_request", "out_acknowledge")
    val guard = if (direction == "two-to-four") policy.returnDelay.fs else 0L
    val marker = timingMarker(id, refs, Map("KIND" -> BigInt(5), "OUTPUT_FS" -> BigInt(guard),
      "A_MIN_FS" -> BigInt(policy.cells.min.fs), "A_MAX_FS" -> BigInt(policy.cells.max.fs),
      "A_MODEL_FS" -> BigInt(policy.cells.model.fs)))
    obligations += ujson.Obj("id" -> id, "kind" -> "phase-conversion-v1", "marker" -> marker,
      "direction" -> direction, "input_request" -> refs(0), "input_acknowledge" -> refs(1),
      "output_request" -> refs(2), "output_acknowledge" -> refs(3),
      "cells" -> ujson.Obj("min_fs" -> policy.cells.min.fs.toString, "max_fs" -> policy.cells.max.fs.toString,
        "model_fs" -> policy.cells.model.fs.toString), "return_delay_fs" -> guard.toString,
      "assumptions" -> "ideal forks; zero latch aperture; sequential full-return conversion; no analog timing claim")
  }

  def encodingTiming(id: String, direction: String, timing: BundledTiming, phase: PhaseTiming): Unit = {
    require(Set("bundled-to-dual", "dual-to-bundled").contains(direction), "invalid encoding direction")
    claim(id)
    val decode = direction == "dual-to-bundled"
    val refs = if (decode) Seq("in_one", "in_zero", "in_acknowledge", "out_data", "out_request", "out_acknowledge")
      else Seq("in_data", "in_request", "in_acknowledge", "out_one", "out_zero", "out_acknowledge")
    def bounds(value: DelayBounds): ujson.Value = ujson.Obj("min_fs" -> value.min.fs.toString,
      "max_fs" -> value.max.fs.toString, "model_fs" -> value.model.fs.toString)
    val guard = if (decode) phase.returnDelay.fs else 0L
    val marker = timingMarker(id, refs, Map("KIND" -> BigInt(if (decode) 7 else 6),
      "OUTPUT_FS" -> BigInt(guard), "MATCHED_FS" -> BigInt(timing.matchedDelay.fs),
      "A_MIN_FS" -> BigInt(phase.cells.min.fs), "A_MAX_FS" -> BigInt(phase.cells.max.fs),
      "A_MODEL_FS" -> BigInt(phase.cells.model.fs), "DATA_MIN_FS" -> BigInt(timing.dataDelay.min.fs),
      "DATA_MAX_FS" -> BigInt(timing.dataDelay.max.fs), "DATA_MODEL_FS" -> BigInt(timing.dataDelay.model.fs)))
    obligations += ujson.Obj("id" -> id, "kind" -> "encoding-boundary-v1", "marker" -> marker,
      "direction" -> direction, "input_data" -> refs(0), "input_control" -> refs(1), "input_acknowledge" -> refs(2),
      "output_data" -> refs(3), "output_control" -> refs(4), "output_acknowledge" -> refs(5),
      "cells" -> bounds(phase.cells), "data_delay" -> bounds(timing.dataDelay),
      "matched_delay_fs" -> timing.matchedDelay.fs.toString, "return_delay_fs" -> guard.toString,
      "assumptions" -> "monotonic RTZ rails; all-valid/all-spacer completion; ideal forks; matched delay guards decoder admission and storage request; decoder latch and storage data delays are additive")
  }

  private def timingMarker(id: String, refs: Seq[String], values: Map[String, BigInt]): String = {
    val signals = refs.map(ref => endpoints.find(_._1 == ref).get._2)
    val parameters = TimingMarker.defaults ++ values + ("WIDTH" -> BigInt(signals.map(_.getWidth).sum))
    val marker = Module(new TimingMarker(parameters))
    marker.reset := owner.reset
    marker.values := chisel3.util.Cat(signals.reverse.map(_.asUInt))
    val markerId = s"${id}_marker"
    val resetRef = endpoints.find(_._2 eq owner.reset).map(_._1)
      .getOrElse(throw new IllegalArgumentException("timing marker requires a registered reset endpoint"))
    primitive(markerId, marker, parameters, resetRef,
      "passive constraint carrier; endpoint list packed least-significant first; no hardware behavior", "constraint-marker")
    markerId
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

  private[chiselasync] def json: ujson.Value = jsonAt(Vector.empty)

  /** Independent inventory of actual elaborated hardware ports, not channel records.
    * CIRCT erases SInt port signedness; preserve that Chisel fact before lowering.
    */
  private[chiselasync] def portAbi: Seq[ujson.Value] = {
    val ports = ArrayBuffer.empty[ujson.Value]
    def visit(value: Data): Unit = {
      if (!DataMirror.hasProbeTypeModifier(value)) value match {
        case record: Record => record.elements.values.foreach(visit)
        case vector: Vec[_] => vector.foreach(visit)
        case _ => ports += ujson.Obj("source" -> value.toTarget.serialize,
          "width" -> value.getWidth, "signed" -> value.isInstanceOf[SInt],
          "direction" -> DataMirror.directionOf(value).toString.toLowerCase,
          "clock" -> value.isInstanceOf[Clock])
      }
    }
    DataMirror.modulePorts(owner).foreach { case (_, data) => visit(data) }
    Seq(ujson.Obj("rtl_path" -> owner.pathName, "module" -> owner.name,
      "ports" -> ujson.Arr.from(ports))) ++ children.flatMap(_._2.contract.portAbi)
  }

  private def jsonAt(prefix: Vector[String]): ujson.Value = ujson.Obj(
    "rtl_path" -> owner.pathName, "module" -> owner.name, "reset_domain" -> owner.resetDomain.id,
    "capacity" -> storageCapacity.map(n => ujson.Num(n)).getOrElse(ujson.Null),
    "endpoints" -> ujson.Arr.from(endpoints.map { case (id, source, anchor) =>
      ujson.Obj("id" -> id, "rtl_path" -> anchor.pathName, "width" -> anchor.getWidth,
        "source" -> source.toTarget.serialize, "probe" -> probeName(prefix :+ id))
    }), "channels" -> ujson.Arr.from(channels.map(_())),
    "primitives" -> ujson.Arr.from(primitives.map(_())), "timing" -> ujson.Arr.from(obligations),
    "children" -> ujson.Arr.from(children.map { case (id, module) =>
      ujson.Obj("id" -> id, "contract" -> module.contract.jsonAt(prefix :+ id))
    }))
}
