import chiselasync.metadata.{AsicMapping, TimingConstraints}
import java.nio.file.{Files, Paths}

/** Inventory the public pipeline and GCD before selecting technology cells.
  * This uses the same published-JAR designs as the digital consumer tests.
  */
object PrepareAsicReference {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "Usage: PrepareAsicReference NEW_OUTPUT_DIRECTORY")
    val root = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(root), "REFERENCE_OUTPUT_ALREADY_EXISTS")
    Seq("pipeline" -> (() => new AddPipeline), "gcd" -> (() => new Gcd)).foreach { case(name,gen) =>
      val base = root.resolve(name)
      val mapping = AsicMapping.prepare(gen(),base)
      val timing = TimingConstraints.prepare(base.resolve("simulation/contract.json"))
      Files.writeString(base.resolve("timing-bindings-required.json"),ujson.write(ujson.Arr.from(
        timing.required.map(e => ujson.Obj("id" -> e.id,"width" -> e.width,"description" -> e.description))),indent=2)+"\n")
      println(s"$name: ${mapping.required.size} cell specializations, ${timing.rules.size} timing paths, ${timing.orderings.size} relative checks: $base")
    }
  }
}
