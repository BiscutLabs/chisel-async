// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chisel3.util.Cat
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ClickTiming, ModelTime}
import chiselasync.primitives.{ControlGate, EventRegister, GateOperation, PhaseRegister, XorGate}
import chiselasync.protocol.{Channel, Payload, TwoPhase}

/** Shared implementation of the published single-phase and phase-decoupled Click
  * templates (Peeters et al., ASYNC 2010; Sparso, chapter 9, figures 9.4b/9.11b).
  * Primitive boundaries preserve the comparator/AND pulse circuit. Every payload
  * capture and phase update is triggered by that local pulse, without adapters.
  */
abstract class NativeClickStage[A <: Data, B <: Data] private[bundled] (
    inGen: A, outGen: B, transform: A => B, val timing: ClickTiming,
    val phaseDecoupled: Boolean, val initial: Option[B], domain: ResetDomain) extends AsyncModule(domain) {
  require(phaseDecoupled || initial.isEmpty, "STANDARD_CLICK_INITIAL_TOKEN_REQUIRES_PHASE_DECOUPLING")
  val in = IO(Flipped(new Channel(inGen,resetDomain).twoPhase))
  val out = IO(new Channel(outGen,resetDomain).twoPhase)
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
  contract.twoPhaseChannel("in",in,"input"); contract.twoPhaseChannel("out",out,"output")
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

/** Native standard Click stage: one phase flip-flop drives both handshake phases.
  * Resets empty. The transform may change payload type, with exact output width.
  */
class ClickStage[A <: Data,B <: Data](a: A,b: B,transform: A => B,timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root"))
    extends NativeClickStage(a,b,transform,timing,false,None,domain)

/** Native phase-decoupled Click stage: independent input/output phase flip-flops.
  * An optional output-typed literal installs one token per reset epoch. Seeded
  * stages expose start.get; release it only after coordinated reset has settled.
  */
class PhaseDecoupledClickStage[A <: Data,B <: Data](a: A,b: B,transform: A => B,timing: ClickTiming,
    initial: Option[B] = None,domain: ResetDomain = new ResetDomain("root"))
    extends NativeClickStage(a,b,transform,timing,true,initial,domain)

/** One-slot identity-transform standard Click register. */
class ClickBuffer[T <: Data](gen: T,timing: ClickTiming,domain: ResetDomain = new ResetDomain("root"))
    extends ClickStage(gen,gen,(x:T)=>x,timing,domain)

/** One-slot identity-transform phase-decoupled Click register, optionally seeded. */
class PhaseDecoupledClickBuffer[T <: Data](gen: T,timing: ClickTiming,initial: Option[T] = None,
    domain: ResetDomain = new ResetDomain("root"))
    extends PhaseDecoupledClickStage(gen,gen,(x:T)=>x,timing,initial,domain)

/** Positive-depth FIFO composed entirely of native standard Click registers. */
class ClickFifo[T <: Data](gen: T,val depth: Int,timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(depth>0,"CLICK_FIFO_DEPTH")
  val in=IO(Flipped(new Channel(gen,resetDomain).twoPhase)); val out=IO(new Channel(gen,resetDomain).twoPhase)
  contract.twoPhaseChannel("in",in,"input"); contract.twoPhaseChannel("out",out,"output"); contract.endpoint("reset",reset)
  contract.capacity(depth)
  private val stages=Seq.tabulate(depth)(i=>asyncChild(s"stage$i")(d=>new ClickBuffer(gen,timing,d)))
  TwoPhase.connect(stages.head.in,in)
  stages.sliding(2).filter(_.size==2).foreach(s=>TwoPhase.connect(s(1).in,s(0).out))
  TwoPhase.connect(out,stages.last.out)
}

/** Positive-depth empty FIFO composed entirely of phase-decoupled Click registers.
  * Use explicitly seeded stages when constructing initialized feedback networks.
  */
class PhaseDecoupledClickFifo[T <: Data](gen: T,val depth: Int,timing: ClickTiming,
    domain: ResetDomain = new ResetDomain("root")) extends AsyncModule(domain) {
  require(depth>0,"CLICK_FIFO_DEPTH")
  val in=IO(Flipped(new Channel(gen,resetDomain).twoPhase)); val out=IO(new Channel(gen,resetDomain).twoPhase)
  contract.twoPhaseChannel("in",in,"input"); contract.twoPhaseChannel("out",out,"output"); contract.endpoint("reset",reset)
  contract.capacity(depth)
  private val stages=Seq.tabulate(depth)(i=>asyncChild(s"stage$i")(d=>new PhaseDecoupledClickBuffer(gen,timing,domain=d)))
  TwoPhase.connect(stages.head.in,in)
  stages.sliding(2).filter(_.size==2).foreach(s=>TwoPhase.connect(s(1).in,s(0).out))
  TwoPhase.connect(out,stages.last.out)
}
