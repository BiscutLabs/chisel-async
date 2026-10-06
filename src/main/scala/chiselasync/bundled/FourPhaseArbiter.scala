// SPDX-License-Identifier: Apache-2.0
package chiselasync.bundled

import chisel3._
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{BundledTiming, ModelTime}
import chiselasync.primitives.{Mutex, MutexPolicy}
import chiselasync.protocol.{Channel, FourPhase}

/** Two-client handshake arbiter: MUTEX + return interlocks + buffered exclusive merge.
  * Topology follows Sparso/Furber tutorial Fig. 5.21. Only the MUTEX has a finite
  * digital choice policy; no bounded physical arbitration latency is promised.
  */
class FourPhaseArbiter[T <: Data](gen: T, timing: BundledTiming, cellDelay: ModelTime,
    resolution: ModelTime, policy: MutexPolicy.Value,
    domain: ResetDomain = new ResetDomain("root"), seed: Long = 1L,
    resolutionJitter: ModelTime = ModelTime(0)) extends AsyncModule(domain) {
  val in = IO(Flipped(Vec(2, new Channel(gen, resetDomain).bundled)))
  val out = IO(new Channel(gen, resetDomain).bundled)
  private val cells = new CompositionCells(this, cellDelay)
  private val mutex = Module(new Mutex(resolution, policy, seed, resolutionJitter))
  mutex.reset := reset; mutex.request := VecInit(in.map(_.req)).asUInt
  contract.primitive("mutex", mutex, Map("RESOLVE_FS" -> BigInt(resolution.fs),
    "POLICY" -> BigInt(policy.id), "SEED" -> BigInt(seed),
    "RESOLVE_MAX_FS" -> (BigInt(resolution.fs) + resolutionJitter.fs)), "reset",
    "finite digital arbitration choices; persistent requests; one-hot grants; no physical resolution-time bound")
  private val merge = asyncChild("merge")(d => new FourPhaseMerge(gen, 2, timing, cellDelay, d))
  for (i <- 0 until 2) {
    merge.in(i).req := cells.and(s"interlock$i", Seq(mutex.grant(i), merge.in(1-i).ack), invert = 2)
    merge.in(i).bits := in(i).bits
    in(i).ack := merge.in(i).ack
    contract.channel(s"in$i", in(i), "input")
  }
  FourPhase.connect(out, merge.out)
  contract.capacity(1); contract.channel("out", out, "output")
}
