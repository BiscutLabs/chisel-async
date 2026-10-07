ThisBuild / scalaVersion := "2.13.18"
val chiselVersion = "7.16.0"

libraryDependencies ++= Seq(
  "io.github.biscutlabs" %% "chisel-async" % "0.1.0-RC1",
  "org.scalatest" %% "scalatest" % "3.2.20" % Test
)
addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % chiselVersion cross CrossVersion.full)
scalacOptions ++= Seq("-deprecation", "-feature", "-unchecked", "-Ymacro-annotations")
Test / parallelExecution := false
publish / skip := true
