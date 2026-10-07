import chisel3._
import chiselasync.bundled.LongHoldBuffer
import chiselasync.metadata.{AsicMapping, BundledTiming, ModelTime}
import chiselasync.primitives.{ControlGate, GateOperation}
import java.nio.file.Files
import org.scalatest.funsuite.AnyFunSuite
import scala.sys.process._

class AsicMappingSpec extends AnyFunSuite {
  test("ASIC inventory rejects an unregistered instance of a known primitive") {
    val error = intercept[IllegalArgumentException] {
      AsicMapping.prepare(new LongHoldBuffer(UInt(8.W),BundledTiming.Simulation) {
        val extra = IO(Output(Bool()))
        private val hidden = Module(new ControlGate(1,GateOperation.Buffer,ModelTime.ps(1000)))
        hidden.reset := reset; hidden.a := in.req; hidden.b := 0.U; extra := hidden.q.asBool
      }, Files.createTempDirectory("asic-unregistered-"))
    }
    assert(error.getMessage.contains("UNREGISTERED_ASIC_PRIMITIVE"))
  }
  test("ASIC export requires exhaustive technology bindings and excludes behavioral models") {
    val root = Files.createTempDirectory("asic-interface-")
    val plan = AsicMapping.prepare(new LongHoldBuffer(UInt(8.W),BundledTiming.Simulation),root)
    val tech = root.resolve("test_cells.sv")
    val bindings = plan.required.zipWithIndex.map { case (cell,i) =>
      AsicMapping.Binding(cell.key,s"TestOnlyCell$i",cell.ports.map(p => p.name -> s"pin_${p.name}").toMap,
        "interface-test black boxes; NOT physical cells")
    }
    Files.writeString(tech,plan.required.zip(bindings).map { case (r,b) =>
      s"(* blackbox *) module ${b.module} (${r.ports.map(p => s"${p.direction} wire [${p.width-1}:0] ${b.pins(p.name)}").mkString(",")}); endmodule"
    }.mkString("\n"))
    val missing = intercept[IllegalArgumentException] { plan.emit(bindings.drop(1),Seq(tech)) }
    assert(missing.getMessage.contains("INCOMPLETE_OR_EXTRA_CELL_BINDINGS"))
    val pins = intercept[IllegalArgumentException] { plan.emit(bindings.updated(0,bindings.head.copy(pins=Map.empty)),Seq(tech)) }
    assert(pins.getMessage.contains("INCOMPLETE_CELL_PIN_MAP"))
    val directory = plan.emit(bindings,Seq(tech))
    import scala.jdk.CollectionConverters._
    val sources = Files.readAllLines(directory.resolve("filelist.f")).asScala.map(directory.resolve(_))
    assert(sources.forall(p => !Files.readString(p).contains("assign #")))
    assert(!sources.exists(_.getFileName.toString.startsWith("ref_")))
    val result = Seq("iverilog","-g2012","-DSYNTHESIS","-s","LongHoldBuffer","-o",directory.resolve("mapped.vvp").toString) ++ sources.map(_.toString)
    assert(Process(result).! == 0)
    val record = ujson.read(Files.readString(directory.resolve("mapping.json")))
    assert(record("status").str == "mapped-unqualified")
    assert(record("bindings").arr.size == plan.required.size)
    val original = root.resolve("simulation/LongHoldBuffer.sv")
    Files.writeString(original,Files.readString(original) + "\n// changed after preparation\n")
    val changed = intercept[IllegalArgumentException] { plan.emit(bindings,Seq(tech)) }
    assert(changed.getMessage.contains("MAPPING_INPUT_CHANGED"))
  }
}
