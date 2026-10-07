ThisBuild / scalaVersion := "2.13.18"
ThisBuild / version := "0.1.0-RC1"
ThisBuild / organization := "io.github.biscutlabs"
ThisBuild / licenses := Seq("Apache-2.0" -> url("https://www.apache.org/licenses/LICENSE-2.0"))
ThisBuild / versionScheme := Some("early-semver")
ThisBuild / homepage := Some(url("https://github.com/BiscutLabs/chisel-async"))
ThisBuild / scmInfo := Some(ScmInfo(
  url("https://github.com/BiscutLabs/chisel-async"),
  "scm:git:https://github.com/BiscutLabs/chisel-async.git",
  Some("scm:git:ssh://git@github.com/BiscutLabs/chisel-async.git")
))
ThisBuild / developers := List(Developer(
  "biscutlabs", "BiscutLabs contributors", "", url("https://github.com/BiscutLabs")
))
ThisBuild / pomIncludeRepository := (_ => false)

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
    description := "Typed asynchronous hardware components and digital simulation models for Chisel",
    publishMavenStyle := true,
    Compile / doc / scalacOptions ++= Seq(
      "-doc-title", "chisel-async Scala API",
      "-doc-version", version.value
    ),
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
