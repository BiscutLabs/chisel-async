package chiselasync

import chisel3._
import chiselasync.bundled.LongHoldBuffer
import chiselasync.metadata._
import java.nio.file.{Files, Path, Paths}
import org.scalatest.funsuite.AnyFunSuite

// A zero exit is deliberately insufficient. This process performs no analysis.
object EmptyStaProcess {
  def main(args: Array[String]): Unit = println("Tool exited normally without checking a path")
}

class OpenStaSpec extends AnyFunSuite {
  private def prepared(): (Path,Path) = {
    val root=Files.createTempDirectory("ca-sta-runner-")
    ExportDesign.emit(new LongHoldBuffer(UInt(2.W),BundledTiming.Simulation),root.resolve("export"))
    val plan=TimingConstraints.prepare(root.resolve("export/contract.json"))
    val pins=plan.required.map(e => e.id -> (0 until e.width).map(i => TimingConstraints.ObjectRef("pin",s"mapped/${e.id}[$i]"))).toMap
    (root,plan.emit(pins,root.resolve("constraints")))
  }
  test("a zero tool exit without complete timing evidence is an error") {
    val (root,constraints)=prepared()
    val input=root.resolve("input.txt"); Files.writeString(input,"test fixture")
    val javaExe=Paths.get(System.getProperty("java.home"),"bin",if(System.getProperty("os.name").startsWith("Windows")) "java.exe" else "java")
    val classpath=Seq(EmptyStaProcess.getClass, classOf[scala.Option[_]]).map(c =>
      Paths.get(c.getProtectionDomain.getCodeSource.getLocation.toURI).toString).mkString(java.io.File.pathSeparator)
    val error=intercept[IllegalArgumentException] {
      OpenSta.check(constraints,OpenSta.Corner("test",Seq(input),input,input),root.resolve("result"),
        Seq(javaExe.toString,"-cp",classpath,"chiselasync.EmptyStaProcess"))
    }
    assert(error.getMessage.contains("STA_INCOMPLETE_RESULT_INVENTORY"),error.getMessage)
    assert(ujson.read(Files.readString(root.resolve("result/result.json")))("status").str=="ERROR")
  }
  test("a changed generated checker is rejected before tool execution") {
    val (root,constraints)=prepared()
    Files.writeString(constraints.resolve("check-timing.tcl"),"puts false-success")
    val error=intercept[IllegalArgumentException] {
      OpenSta.check(constraints,OpenSta.Corner("test",Seq.empty,root,root),root.resolve("result"))
    }
    assert(error.getMessage.contains("CONSTRAINT_FILE_CHANGED"))
    assert(!Files.exists(root.resolve("result")))
  }
}
