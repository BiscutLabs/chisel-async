"""orfs_async_flow: an orfs_flow for a chisel-async design."""

load("@bazel-orfs//:openroad.bzl", "orfs_flow")
load("@rules_shell//shell:sh_test.bzl", "sh_test")

def _lib(pdk, name):
    return "@orfs//flow:platforms/{}/lib/{}".format(pdk, name)

# The liberty files for the contract check, by corner: the corners ORFS's
# platforms ship. Each corner is a separate OpenSTA run, as the library asks.
LIBERTY = {
    "asap7": {
        corner: [_lib("asap7", "NLDM/asap7sc7p5t_{}_RVT_{}_nldm_{}".format(group, corner.upper(), date)) for group, date in [
            ("AO", "211120.lib.gz"),
            ("INVBUF", "220122.lib.gz"),
            ("OA", "211120.lib.gz"),
            ("SIMPLE", "211120.lib.gz"),
            ("SEQ", "220123.lib"),
        ]]
        for corner in ["ff", "ss"]
    },
    "gf180": {
        "ff": [_lib("gf180", "gf180mcu_fd_sc_mcu7t5v0__ff_n40C_5v50.lib.gz")],
        "ss": [_lib("gf180", "gf180mcu_fd_sc_mcu7t5v0__ss_125C_4v50.lib.gz")],
    },
}

# The quick end of ORFS: no fill, no sign-off reports.
FAST_SETTINGS = {
    "FILL_CELLS": "",
    "GND_NETS_VOLTAGES": "",
    "GPL_ROUTABILITY_DRIVEN": "0",
    "GPL_TIMING_DRIVEN": "0",
    "PWR_NETS_VOLTAGES": "",
    "SKIP_CTS_REPAIR_TIMING": "1",
    "SKIP_INCREMENTAL_REPAIR": "1",
    "SKIP_REPORT_METRICS": "1",
    "TAPCELL_TCL": "",
}

def orfs_async_flow(name, export, top, pdk, arguments = {}, signoff_tags = [], **kwargs):
    """Place and route a chisel-async export.

    Args:
      name: base name of the flow targets (<name>_synth ... <name>_final)
      export: a chisel_async_run target running //openroad:export
      top: the design's top module
      pdk: the ORFS platform, e.g. "asap7" or "gf180"
      arguments: ORFS variables on top of FAST_SETTINGS
      signoff_tags: tags for the contract-check targets and tests
      **kwargs: passed to orfs_flow
    """
    native.genrule(
        name = name + "_rtl",
        srcs = [export],
        outs = [name + ".sv"],
        cmd = "cp $(location {})/export/design.sv $@".format(export),
    )
    orfs_flow(
        name = name,
        top = top,
        pdk = "@orfs//flow:" + pdk,
        verilog_files = [name + "_rtl"],
        sources = {
            "PRE_FLOORPLAN_TCL": [Label("//openroad:preserve.tcl")],
            "SDC_FILE": [Label("//openroad:async.sdc")],
        },
        # Read by ORFS's synth.tcl but missing from its variables.yaml.
        user_sources = {
            "SYNTH_POST_HIERARCHY_SCRIPTS": [Label("//openroad:flatten.ys")],
        },
        arguments = FAST_SETTINGS | arguments,
        **kwargs
    )
    chisel_async_flat(
        name = name + "_flat",
        export = export,
        top = top,
    )
    chisel_async_images(
        name = name + "_images",
        export = export,
        final = name + "_final",
    )
    for corner, liberty in LIBERTY[pdk].items():
        chisel_async_signoff(
            name = "{}_signoff_{}".format(name, corner),
            corner = corner,
            export = export,
            final = name + "_final",
            flat = name + "_flat",
            liberty = liberty,
            tags = signoff_tags,
        )
        sh_test(
            name = "{}_signoff_{}_test".format(name, corner),
            srcs = [Label("//openroad:signoff_test.sh")],
            args = ["$(rootpath {}_signoff_{})/check".format(name, corner)],
            data = ["{}_signoff_{}".format(name, corner)],
            tags = signoff_tags,
        )

def _flat_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".json")
    script = ctx.actions.declare_file(ctx.label.name + ".ys")
    export = ctx.file.export
    ctx.actions.write(script, "\n".join([
        "plugin -i {}".format(ctx.file._slang.path),
        "read_verilog -lib {export}/export/cells.v".format(export = export.path),
        "read_slang -D SYNTHESIS --keep-hierarchy --compat=vcs --ignore-assertions --top {top} {export}/export/design.sv".format(
            top = ctx.attr.top,
            export = export.path,
        ),
        "setattr -unset keep_hierarchy",
        "setattr -mod -unset keep_hierarchy",
        "hierarchy -top {}".format(ctx.attr.top),
        "flatten",
        "write_json {}".format(out.path),
        "",
    ]))
    ctx.actions.run(
        executable = ctx.executable._yosys,
        arguments = ["-q", "-s", script.path],
        inputs = [export, script, ctx.file._slang],
        outputs = [out],
        mnemonic = "ChiselAsyncFlatten",
    )
    return [DefaultInfo(files = depset([out]))]

chisel_async_flat = rule(
    implementation = _flat_impl,
    doc = "The mapped RTL of an export, flattened by yosys before any optimization: names intact.",
    attrs = {
        "export": attr.label(mandatory = True, allow_single_file = True),
        "top": attr.string(mandatory = True),
        "_slang": attr.label(default = "@sv-elab//src/yosys_plugin:slang.so", allow_single_file = True),
        "_yosys": attr.label(default = "@yosys//:yosys", executable = True, cfg = "exec"),
    },
)

def _signoff_impl(ctx):
    out = ctx.actions.declare_directory(ctx.label.name)
    final = ctx.files.final

    def pick(suffix):
        found = [f for f in final if f.basename == suffix]
        if len(found) != 1:
            fail("{}: expected one {} in {}".format(ctx.label, suffix, ctx.attr.final.label))
        return found[0]

    netlist = pick("6_final.v")
    spef = pick("6_final.spef")
    ctx.actions.run_shell(
        command = """
export HOME="$PWD/{out}/.home"; mkdir -p "$HOME"
{tool} {export}/export {flat} {netlist} {spef} {setup} {sta} {out}/check {corner} {libs} > {out}/signoff.log 2>&1 || true
rm -rf "$HOME"
""".format(
            tool = ctx.executable._signoff.path,
            export = ctx.file.export.path,
            flat = ctx.file.flat.path,
            netlist = netlist.path,
            spef = spef.path,
            setup = ctx.file._setup.path,
            sta = ctx.executable._sta.path,
            out = out.path,
            corner = ctx.attr.corner,
            libs = " ".join([f.path for f in ctx.files.liberty]),
        ),
        inputs = [ctx.file.export, ctx.file.flat, netlist, spef, ctx.file._setup] + ctx.files.liberty,
        tools = [ctx.attr._signoff[DefaultInfo].files_to_run, ctx.attr._sta[DefaultInfo].files_to_run],
        outputs = [out],
        mnemonic = "ChiselAsyncSignoff",
        progress_message = "Checking the timing contract of %{label}",
    )
    return [DefaultInfo(files = depset([out]))]

chisel_async_signoff = rule(
    implementation = _signoff_impl,
    doc = """The library's timing contract, checked on the routed netlist with SPEF at one corner.

    Never fails the build: the result is in <name>/check/sta/result.json, and
    a test reads it.""",
    attrs = {
        "corner": attr.string(mandatory = True),
        "export": attr.label(mandatory = True, allow_single_file = True),
        "final": attr.label(mandatory = True),
        "flat": attr.label(mandatory = True, allow_single_file = True),
        "liberty": attr.label_list(allow_files = True, mandatory = True),
        "_setup": attr.label(default = "//openroad:corner.tcl", allow_single_file = True),
        "_signoff": attr.label(default = "//openroad:signoff", executable = True, cfg = "exec"),
        "_sta": attr.label(default = "@openroad//src/sta:opensta", executable = True, cfg = "exec"),
    },
)

def _images_impl(ctx):
    out = ctx.actions.declare_directory(ctx.label.name)
    odb = [f for f in ctx.files.final if f.basename == "6_final.odb"]
    if len(odb) != 1:
        fail("{}: expected one 6_final.odb".format(ctx.label))
    ctx.actions.run_shell(
        command = """
export QT_QPA_PLATFORM=offscreen HOME="$PWD/{out}/.home" ODB={odb} OUT_DIR={out} KINDS={export}/export/kinds.tcl
mkdir -p "$HOME"
{openroad} -gui -no_splash -no_init {script} > {out}/images.log 2>&1
rm -rf "$HOME"
""".format(
            out = out.path,
            odb = odb[0].path,
            export = ctx.file.export.path,
            openroad = ctx.executable._openroad.path,
            script = ctx.file._script.path,
        ),
        inputs = odb + [ctx.file._script, ctx.file.export],
        tools = [ctx.attr._openroad[DefaultInfo].files_to_run],
        outputs = [out],
        mnemonic = "ChiselAsyncImages",
        progress_message = "Drawing %{label}",
    )
    return [DefaultInfo(files = depset([out]))]

chisel_async_images = rule(
    implementation = _images_impl,
    doc = "Layout images of a routed design: routed.png and primitives.png.",
    attrs = {
        "export": attr.label(mandatory = True, allow_single_file = True),
        "final": attr.label(mandatory = True),
        "_openroad": attr.label(default = "@openroad//:openroad", executable = True, cfg = "exec"),
        "_script": attr.label(default = "//openroad:images.tcl", allow_single_file = True),
    },
)
