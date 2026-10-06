// SPDX-License-Identifier: Apache-2.0
package chiselasync

import chisel3._
import chiselasync.bundled.FourPhaseBuffer
import chiselasync.core.{AsyncModule, ResetDomain}
import chiselasync.metadata.{ExportDesign, ModelTime}
import chiselasync.primitives.{DelayLine, Latch}
import chiselasync.protocol.FourPhase
import circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite

class ExportSpec extends AnyFunSuite {
  test("time uses exact nonnegative signed 64-bit femtoseconds") {
    assert(ModelTime.ps(8).fs == 8000)
    assert(ModelTime.ps(8).ticks(ModelTime(1000)) == 8)
    assert(ModelTime(Long.MaxValue).fs == Long.MaxValue)
    intercept[IllegalArgumentException](ModelTime(-1))
    intercept[IllegalArgumentException](ModelTime(1001).ticks(ModelTime(1000)))
    intercept[IllegalArgumentException](ModelTime(1).ticks(ModelTime(0)))
    intercept[ArithmeticException](ModelTime.ps(Long.MaxValue))
    intercept[ArithmeticException](ModelTime(Long.MaxValue) + ModelTime(1))
  }

  test("matching domain labels do not authorize independently reset channels") {
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val in = IO(Flipped(new FourPhase(UInt(8.W), Some(new ResetDomain("root")))))
        val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
        FourPhase.connect(out, in)
      })
    }
    assert(error.getMessage.contains("reset domains differ"))
  }

  test("scoped channels connect and an unbound export channel is rejected") {
    ChiselStage.emitCHIRRTL(new AsyncModule {
      val in = IO(Flipped(new FourPhase(UInt(8.W), Some(resetDomain))))
      val out = IO(new FourPhase(UInt(8.W), Some(resetDomain)))
      FourPhase.connect(out, in)
      contract.channel("in", in, "input")
    })
    val error = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val in = IO(Flipped(new FourPhase(UInt(8.W))))
        in.ack := false.B
        contract.channel("in", in, "input")
      })
    }
    assert(error.getMessage.contains("unbound reset domain"))
  }

  test("child factory shares and wires the parent reset domain") {
    ChiselStage.emitCHIRRTL(new AsyncModule {
      val first = asyncChild("first")(domain => new FourPhaseBuffer(UInt(8.W), domain))
      val second = asyncChild("second")(domain => new FourPhaseBuffer(UInt(8.W), domain))
      assert((first.resetDomain eq resetDomain) && (second.resetDomain eq resetDomain))
      first.in.req := false.B
      first.in.bits := 0.U
      second.out.ack := false.B
      FourPhase.connect(second.in, first.out)
    })
    val ignoredDomain = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        val child = asyncChild("wrong")(_ => new FourPhaseBuffer(UInt(8.W)))
      })
    }
    assert(ignoredDomain.getMessage.contains("child reset domains differ"))
  }

  test("registry rejects duplicate semantic IDs and missing timing endpoints") {
    val duplicate = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        contract.endpoint("reset", reset)
        contract.endpoint("reset", reset)
      })
    }
    assert(duplicate.getMessage.contains("duplicate semantic ID"))
    val missing = intercept[IllegalArgumentException] {
      ChiselStage.emitCHIRRTL(new AsyncModule {
        contract.setupHold("test", "absent", "absent", "absent", "absent", "absent", ModelTime(1), ModelTime(1))
      })
    }
    assert(missing.getMessage.contains("missing timing endpoint"))
  }

  test("primitives reject invalid widths, delays and reset values and package their views") {
    intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new RawModule {
      val cell = Module(new DelayLine(0, ModelTime(1)))
    }))
    intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new RawModule {
      val cell = Module(new DelayLine(1, ModelTime(0)))
    }))
    intercept[IllegalArgumentException](ChiselStage.emitCHIRRTL(new RawModule {
      val cell = Module(new Latch(8, 256))
    }))
    Seq("ChiselAsyncLatch_v1", "ChiselAsyncDelayLine_v1").foreach { model =>
      assert(getClass.getResource(s"/chiselasync/sv/$model.sv") != null)
    }
  }

  test("independent exports have stable manifests across widths, repeated elaboration and paths with spaces") {
    val root = Paths.get("target", "export-spec")
    Files.createDirectories(root)
    val first = Files.createTempDirectory(root, "first ")
    val other = Files.createTempDirectory(root, "other ")
    val repeated = Files.createTempDirectory(root, "repeat ")
    ExportDesign.emit(new FourPhaseBuffer(UInt(8.W)), first)
    ExportDesign.emit(new FourPhaseBuffer(UInt(65.W)), other)
    ExportDesign.emit(new FourPhaseBuffer(UInt(8.W)), repeated)
    val a = Files.readString(first.resolve("contract.json"))
    val b = Files.readString(other.resolve("contract.json"))
    assert(a == Files.readString(repeated.resolve("contract.json")))
    assert(ujson.read(a)("semantic_sha256") != ujson.read(b)("semantic_sha256"))
    assert(!a.contains(first.toAbsolutePath.toString))
  }

  test("typed port inventory retains nested signed leaves independently of channel layout") {
    class Packet extends Bundle {
      val tag = UInt(3.W)
      val signed = SInt(9.W)
      val lanes = Vec(2, UInt(5.W))
    }
    val root = Paths.get("target", "export-spec")
    Files.createDirectories(root)
    val directory = Files.createTempDirectory(root, "typed ports ")
    ExportDesign.emit(new FourPhaseBuffer(new Packet), directory)
    val abi = ujson.read(Files.readString(directory.resolve("ports.json")))
    val ports = abi("nodes")(0)("ports").arr
    val input = ports.filter(_("source").str.contains(">in.bits")).map { p =>
      p("source").str.split(">", 2)(1) -> (p("width").num.toInt, p("signed").bool, p("direction").str)
    }.toMap
    assert(input == Map("in.bits.tag" -> (3, false, "input"), "in.bits.signed" -> (9, true, "input"),
      "in.bits.lanes[0]" -> (5, false, "input"), "in.bits.lanes[1]" -> (5, false, "input")))
    assert(ports.size == 13 && !ports.exists(_("source").str.contains("ca_p_")))
  }

  test("port ABI reflects channel types without channel registry declarations") {
    class ProtocolPorts extends AsyncModule {
      contract.endpoint("reset", reset)
      val four = IO(Flipped(new chiselasync.protocol.Channel(UInt(8.W), resetDomain).bundled))
      val toggles = IO(Flipped(Vec(2, new chiselasync.protocol.Channel(UInt(8.W), resetDomain).twoPhase)))
      val dual = IO(Flipped(new chiselasync.protocol.Channel(UInt(8.W), resetDomain).dualRail))
      val sync = IO(Flipped(chisel3.util.Decoupled(UInt(8.W))))
      four.ack := false.B; toggles.foreach(_.ack := false.B); dual.ack := false.B; sync.ready := false.B
    }
    val directory = Files.createTempDirectory(Paths.get("target", "export-spec"), "protocol ports ")
    ExportDesign.emit(new ProtocolPorts, directory)
    val abi = ujson.read(Files.readString(directory.resolve("ports.json")))
    assert(abi("schema").str == "chisel-async-port-abi-v2")
    val bindings = abi("nodes")(0)("channels").arr.map(c =>
      c("source").str.split(">", 2)(1) -> c("protocol").str).toMap
    assert(bindings == Map("four" -> "four-phase-bundled-v1", "toggles[0]" -> "two-phase-bundled-v1",
      "toggles[1]" -> "two-phase-bundled-v1", "dual" -> "dual-rail-rtz-v1", "sync" -> "decoupled-v1"))
    assert(ujson.read(Files.readString(directory.resolve("contract.json")))("manifest")("design")("channels").arr.isEmpty)
  }
}
