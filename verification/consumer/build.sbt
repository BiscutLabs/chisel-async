ThisBuild / scalaVersion := "2.13.18"
ThisBuild / version := "0.0.0"
libraryDependencies += "io.github.biscutlabs" %% "chisel-async" % "0.1.0-RC1"
addCompilerPlugin("org.chipsalliance" % "chisel-plugin" % "7.16.0" cross CrossVersion.full)

libraryDependencies += "org.scalatest" %% "scalatest" % "3.2.20" % Test
Test / parallelExecution := false
