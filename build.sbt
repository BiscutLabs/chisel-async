ThisBuild / scalaVersion := "2.13.18"
ThisBuild / version := "0.1.0-SNAPSHOT"
ThisBuild / organization := "io.github.biscutlabs"
ThisBuild / licenses := Seq("Apache-2.0" -> url("https://www.apache.org/licenses/LICENSE-2.0"))

val chiselVersion = "7.16.0"
lazy val commonSettings = Seq(
  libraryDependencies ++= Seq(
    "org.chipsalliance" %% "chisel" % chiselVersion,
    "com.lihaoyi" %% "ujson" % "3.3.1",
    "org.scalatest" %% "scalatest" % "3.2.20" % Test
  ),
  addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % chiselVersion cross CrossVersion.full),
  scalacOptions ++= Seq("-deprecation", "-feature", "-unchecked", "-Xcheckinit", "-Ymacro-annotations"),
  Test / parallelExecution := false
)

lazy val root = (project in file("."))
  .settings(commonSettings)
  .settings(
    name := "chisel-async",
    Compile / packageBin / mappings += baseDirectory.value / "LICENSE" -> "META-INF/LICENSE",
    Compile / packageSrc / mappings += baseDirectory.value / "LICENSE" -> "META-INF/LICENSE"
  )

lazy val examples = (project in file("examples"))
  .dependsOn(root)
  .settings(commonSettings)
  .settings(name := "chisel-async-examples", publish / skip := true)

lazy val simulation = (project in file("verification/chiselsim"))
  .dependsOn(root)
  .settings(commonSettings)
  .settings(name := "chisel-async-simulation", publish / skip := true)
