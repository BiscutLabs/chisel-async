// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.primitives.{ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import chiselasync.protocol.{Payload, TwoPhase}

/** Common ports and state for [[ClickStage]] and [[PhaseDecoupledClickStage]].
  * Instantiate those concrete classes, or their identity buffers, in an
  * [[chiselasync.core.AsyncModule]] using `asyncChild`.
  *
  * One local pulse captures the payload and toggles the phase state. Primitive
  * boundaries preserve the XOR/AND controller in Peeters et al. (ASYNC 2010)
  * and Sparsø, chapter 9, figures 9.4(b)/9.11(b). There is no global clock.
  * Reset discards pending work and reinstalls the optional initial output token.
  *
  * @param inGen unbound input payload type with explicit widths
  * @param outGen unbound output payload type with explicit widths
  * @param transform pure combinational function returning exactly `outGen`'s type and shape
  * @param timing per-cell bounds and local-pulse timing obligations
  * @param phaseDecoupled whether input and output have separate phase registers
  * @param initial optional fully specified output literal, emitted before new input
  * @param domain shared reset identity supplied by the parent's `asyncChild`
  */
abstract class NativeClickStage[A <: Data, B <: Data] private[bundled] (
    inGen: A, outGen: B, transform: A => B, val timing: ClickTiming,
    val phaseDecoupled: Boolean, val initial: Option[B], domain: ResetDomain) extends AsyncModule(domain) {
  require(phaseDecoupled || initial.isEmpty, "STANDARD_CLICK_INITIAL_TOKEN_REQUIRES_PHASE_DECOUPLING")
  /** Input token. Hold data from before either request edge until acknowledgement. */
  val in = twoPhaseInput("in", inGen)
  /** Output token. Data remains stable while request and acknowledgement differ. */
  val out = twoPhaseOutput("out", outGen)
  /** Present only when an initial token is installed. Hold low through reset,
    * raise after the entire domain settles, and keep high until the next reset.
    */
  val start: Option[Bool] = initial.map(_ => IO(Input(Bool())))
  private val transformed = transform(in.bits)
  Payload.validateType(outGen); Payload.requireSame(out.bits, transformed)
  private val resetBits = initial.map { value =>
    Payload.requireSame(out.bits,value)
    require(value.litOption.nonEmpty, "CLICK_INITIAL_REQUIRES_LITERAL")
    value.litValue & ((BigInt(1) << outGen.getWidth) - 1)
  }.getOrElse(BigInt(0))
  contract.capacity(1)
  private val resetRef = contract.endpoint("reset",reset)
  private def buffer(id: String, delay: ModelTime, width: Int = 1, value: BigInt = 0): ControlGate = {
    val c = Module(new ControlGate(width,GateOperation.Buffer,delay,value)); c.reset := reset; c.b := 0.U
    contract.primitive(id,c,Map("WIDTH"->BigInt(width),"OP"->BigInt(0),"DELAY_FS"->BigInt(delay.fs),
      "RESET_VALUE"->value),resetRef,"Click guard or whole-transform digital propagation allowance")
    c
  }
  private def phase(id: String, value: Boolean): PhaseRegister = {
    val delay=timing.cells(id).model
    val c=Module(new PhaseRegister(delay,value)); c.reset:=reset
    contract.primitive(id,c,Map("DELAY_FS"->BigInt(delay.fs),"RESET_VALUE"->BigInt(if(value) 1 else 0)),
      resetRef,"rising local Click pulse toggles phase; explicit initialized parity")
    c
  }
  private def compare(id: String): XorGate = {
    val c=Module(new XorGate(timing.cells(id).model)); c.reset:=reset
    contract.primitive(id,c,Map("DELAY_FS"->BigInt(timing.cells(id).model.fs)),resetRef,"atomic XOR comparator")
    c
  }
  private val request = buffer("request_delay",timing.requestDelay)
  private val data = buffer("data_delay",timing.data.model,outGen.getWidth)
  private val inputPhase = phase("input_phase",false)
  private val outputPhase = if(phaseDecoupled) phase("output_phase",initial.nonEmpty) else inputPhase
  private val pending = compare("input_compare")
  private val occupied = compare("output_compare")
  private val fire = Module(new AtomicAnd(2,timing.controls.fire.model,2))
  fire.reset:=reset
  contract.primitive("fire",fire,Map("INPUTS"->BigInt(2),"DELAY_FS"->BigInt(timing.controls.fire.model.fs),
    "INVERT"->BigInt(2)),resetRef,"Click pulse = input pending AND output empty; preserve atomic input bubble")
  private val payload=Module(new EventRegister(outGen.getWidth,timing.payload.model,resetBits))
  payload.reset:=reset
  contract.primitive("payload",payload,Map("WIDTH"->BigInt(outGen.getWidth),"DELAY_FS"->BigInt(timing.payload.model.fs),
    "RESET_VALUE"->resetBits),resetRef,"positive-edge local-pulse capture; initialized literal when seeded")
  private val acknowledge=buffer("acknowledge_guard",timing.acknowledgeDelay)
  private val offer=buffer("output_guard",timing.outputDelay, value=if(initial.nonEmpty) BigInt(1) else BigInt(0))
  request.a:=in.req.asUInt; data.a:=transformed.asUInt
  pending.a:=request.q.asBool; pending.b:=inputPhase.q
  occupied.a:=outputPhase.q; occupied.b:=out.ack
  fire.d:=Cat(occupied.q,pending.q)
  inputPhase.trigger:=fire.q
  if(phaseDecoupled) outputPhase.trigger:=fire.q
  payload.trigger:=fire.q; payload.d:=data.q
  acknowledge.a:=inputPhase.q.asUInt; in.ack:=acknowledge.q.asBool
  offer.a:=outputPhase.q.asUInt
  out.req:=offer.q.asBool
  start.foreach { go =>
    val barrier=Module(new AtomicAnd(2,timing.controls.fire.model,0))
    barrier.reset:=reset; barrier.d:=Cat(go,offer.q.asBool); out.req:=barrier.q
    contract.primitive("start_barrier",barrier,Map("INPUTS"->BigInt(2),"DELAY_FS"->BigInt(timing.controls.fire.model.fs),
      "INVERT"->BigInt(0)),resetRef,"initial token barrier; start rises once after coordinated reset settles")
    contract.endpoint("start",go)
  }
  out.bits:=payload.q.asTypeOf(outGen)
  private val capture=WireDefault(fire.q)
  private val registerData=WireDefault(UInt(outGen.getWidth.W),data.q)
  contract.endpoint("capture",capture); contract.endpoint("register_data",registerData)
  contract.clickTiming("click",timing,phaseDecoupled,initial.nonEmpty)
}

/** One-slot native standard Click stage, empty after reset.
  * One phase flip-flop drives both handshake phases. Use this for an ordinary
  * two-phase pipeline; use [[PhaseDecoupledClickStage]] to install an initial token.
  * The stage has `in`, `out` and explicit asynchronous `reset` ports; `start` is `None`.
  *
  * {{{
  * val add = asyncChild("add") { domain =>
  *   new ClickStage(
  *     inGen = UInt(8.W), outGen = UInt(9.W),
  *     transform = (x: UInt) => x +& 1.U(8.W),
  *     timing = ClickTiming.Simulation, domain = domain)
  * }
  * }}}
  *
  * @param inGen unbound input payload type with explicit widths
  * @param outGen unbound output payload type with explicit widths
  * @param transform pure combinational function; no implicit resizing is allowed
  * @param timing timing policy; [[chiselasync.metadata.ClickTiming.Simulation]] is a digital example
  * @param domain shared reset identity from `asyncChild`; the default creates a standalone domain
  */
class ClickStage[A <: Data, B <: Data](
    inGen: A,
    outGen: B,
    transform: A => B,
    timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root"))
    extends NativeClickStage(inGen, outGen, transform, timing, false, None, domain)

/** One-slot native Click stage with separate input and output phase flip-flops.
  * Separate phase state permits one initial output token while the input resets
  * empty. The initial literal bypasses `transform`; later inputs use it normally.
  * With `initial = Some(...)`, connect `start.get` to a signal held low through
  * coordinated reset and settling, then high until the next reset. With `None`,
  * the stage resets empty and has no start port.
  *
  * @param inGen unbound input payload type with explicit widths
  * @param outGen unbound output payload type with explicit widths
  * @param transform pure combinational function returning exactly the output type
  * @param timing per-cell bounds and setup/hold, pulse-width and distribution obligations
  * @param initial fully specified literal of `outGen`'s type; reinstated each reset epoch
  * @param domain shared reset identity from `asyncChild`; the default creates a standalone domain
  */
class PhaseDecoupledClickStage[A <: Data, B <: Data](
    inGen: A,
    outGen: B,
    transform: A => B,
    timing: ClickTiming,
    initial: Option[B] = None,
    domain: ResetDomain = new ResetDomain("root"))
    extends NativeClickStage(inGen, outGen, transform, timing, true, initial, domain)

/** One-slot standard Click buffer with an identity transform, empty after reset.
  * @param gen unbound input/output payload type with explicit widths
  * @param timing per-cell bounds and local-pulse timing obligations
  * @param domain shared reset identity from `asyncChild`
  */
class ClickBuffer[T <: Data](
    gen: T, timing: ClickTiming, domain: ResetDomain = new ResetDomain("root"))
    extends ClickStage(gen, gen, (x: T) => x, timing, domain)

/** One-slot phase-decoupled Click buffer with an identity transform.
  * An initial token requires wiring `start.get`; see [[PhaseDecoupledClickStage]].
  * @param gen unbound input/output payload type with explicit widths
  * @param timing per-cell bounds and local-pulse timing obligations
  * @param initial fully specified payload literal, or `None` for an empty buffer
  * @param domain shared reset identity from `asyncChild`
  */
class PhaseDecoupledClickBuffer[T <: Data](
    gen: T, timing: ClickTiming, initial: Option[T] = None,
    domain: ResetDomain = new ResetDomain("root"))
    extends PhaseDecoupledClickStage(gen, gen, (x: T) => x, timing, initial, domain)

/** Ordered FIFO of native standard Click buffers, empty after reset.
  * Each stage stores one token; backpressure propagates when all slots are full.
  * @param gen unbound input/output payload type with explicit widths
  * @param depth positive number of storage slots; zero-depth bypass is not supported
  * @param timing shared policy, with independent simulated delays in each stage
  * @param domain shared reset identity from `asyncChild`
  */
class ClickFifo[T <: Data](
    gen: T, val depth: Int, timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(depth > 0, "CLICK_FIFO_DEPTH")
  /** Incoming tokens, acknowledged only when storage is available. */
  val in = twoPhaseInput("in", gen)
  /** Outgoing tokens in input order; acknowledgement releases storage. */
  val out = twoPhaseOutput("out", gen)
  contract.endpoint("reset", reset)
  contract.capacity(depth)
  private val stages = Seq.tabulate(depth)(i => asyncChild(s"stage$i")(d => new ClickBuffer(gen, timing, d)))
  TwoPhase.connect(stages.head.in, in)
  stages.sliding(2).filter(_.size == 2).foreach(s => TwoPhase.connect(s(1).in, s(0).out))
  TwoPhase.connect(out, stages.last.out)
}

/** Ordered FIFO of native phase-decoupled Click buffers, empty after reset.
  * Use explicitly initialized [[PhaseDecoupledClickBuffer]] instances to build
  * feedback networks. This FIFO has no initial tokens and no start port.
  * @param gen unbound input/output payload type with explicit widths
  * @param depth positive number of storage slots; zero-depth bypass is not supported
  * @param timing shared policy, with independent simulated delays in each stage
  * @param domain shared reset identity from `asyncChild`
  */
class PhaseDecoupledClickFifo[T <: Data](
    gen: T, val depth: Int, timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(depth > 0, "CLICK_FIFO_DEPTH")
  /** Incoming tokens, acknowledged only when storage is available. */
  val in = twoPhaseInput("in", gen)
  /** Outgoing tokens in input order; acknowledgement releases storage. */
  val out = twoPhaseOutput("out", gen)
  contract.endpoint("reset", reset)
  contract.capacity(depth)
  private val stages = Seq.tabulate(depth)(i => asyncChild(s"stage$i")(d =>
    new PhaseDecoupledClickBuffer(gen, timing, domain = d)))
  TwoPhase.connect(stages.head.in, in)
  stages.sliding(2).filter(_.size == 2).foreach(s => TwoPhase.connect(s(1).in, s(0).out))
  TwoPhase.connect(out, stages.last.out)
}
