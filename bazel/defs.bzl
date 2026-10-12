"""Shared settings and a rule to run chisel-async JVM entry points."""

CHISEL_PLUGIN = ["@maven//:org_chipsalliance_chisel_plugin_2_13_18"]

# The same flags as build.sbt's commonSettings.
SCALACOPTS = [
    "-deprecation",
    "-feature",
    "-unchecked",
    "-Xcheckinit",
    "-Ymacro-annotations",
]


def _chisel_async_run_impl(ctx):
    out = ctx.actions.declare_directory(ctx.label.name)
    firtool = ctx.file._firtool
    ctx.actions.run_shell(
        command = """
set -eu
export CHISEL_FIRTOOL_PATH="$PWD/$(dirname {firtool})"
export HOME="$PWD/{out}/.home"
mkdir -p "$HOME"
{tool} {args} > {out}/log.txt 2>&1 || {{ cat {out}/log.txt; exit 1; }}
rm -rf "$HOME"
""".format(
            firtool = firtool.path,
            out = out.path,
            tool = ctx.executable.tool.path,
            args = " ".join([a.replace("$(OUT)", out.path) for a in ctx.attr.args]),
        ),
        inputs = [firtool],
        tools = [ctx.attr.tool[DefaultInfo].files_to_run],
        outputs = [out],
        mnemonic = "ChiselAsync",
        progress_message = "Running %{label}",
    )
    return [DefaultInfo(files = depset([out]))]

chisel_async_run = rule(
    implementation = _chisel_async_run_impl,
    doc = "Runs `tool` with `args` ($(OUT) is the output directory) and firtool 1.160.0 on CHISEL_FIRTOOL_PATH.",
    attrs = {
        "args": attr.string_list(),
        "tool": attr.label(executable = True, cfg = "exec", mandatory = True),
        "_firtool": attr.label(default = "@firtool//:bin/firtool", allow_single_file = True),
    },
)
