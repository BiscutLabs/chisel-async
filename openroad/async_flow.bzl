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
        chisel_async_timed(
            name = "{}_timed_{}".format(name, corner),
            final = name + "_final",
            liberty = liberty,
            signoff = "{}_signoff_{}".format(name, corner),
            tags = signoff_tags,
            top = top,
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
        "_openroad": attr.label(default = "@openroad//:openroad-qt", executable = True, cfg = "exec"),
        "_script": attr.label(default = "//openroad:images.tcl", allow_single_file = True),
    },
)

def _timed_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".v")
    table = ctx.actions.declare_file(ctx.label.name + ".tsv")
    spef = [f for f in ctx.files.final if f.basename == "6_final.spef"]
    if len(spef) != 1:
        fail("{}: expected one 6_final.spef".format(ctx.label))
    signoff = ctx.file.signoff
    ctx.actions.run_shell(
        command = """
set -e
LIBERTY="{libs}" NETLIST={signoff}/check/analysis.v TOP={top} SPEF={spef} OUT={table} \
  {sta} -no_splash -exit {script} > {table}.log 2>&1 || {{ cat {table}.log; exit 1; }}
HOME="$PWD" {timed} {netlist} {table} {out}
""".format(
            libs = " ".join([f.path for f in ctx.files.liberty]),
            signoff = signoff.path,
            top = ctx.attr.top,
            spef = spef[0].path,
            table = table.path,
            sta = ctx.executable._sta.path,
            script = ctx.file._script.path,
            timed = ctx.executable._timed.path,
            netlist = [f for f in ctx.files.final if f.basename == "6_final.v"][0].path,
            out = out.path,
        ),
        inputs = [signoff, spef[0], ctx.file._script] + ctx.files.liberty + ctx.files.final,
        tools = [ctx.attr._sta[DefaultInfo].files_to_run, ctx.attr._timed[DefaultInfo].files_to_run],
        outputs = [out, table],
        mnemonic = "ChiselAsyncTimed",
    )
    return [DefaultInfo(files = depset([out]))]

chisel_async_timed = rule(
    implementation = _timed_impl,
    doc = "The routed netlist with per-output rise/fall delays from STA, for event simulation.",
    attrs = {
        "final": attr.label(mandatory = True),
        "liberty": attr.label_list(allow_files = True, mandatory = True),
        "signoff": attr.label(mandatory = True, allow_single_file = True),
        "top": attr.string(mandatory = True),
        "_script": attr.label(default = "//openroad:delays.tcl", allow_single_file = True),
        "_sta": attr.label(default = "@openroad//src/sta:opensta", executable = True, cfg = "exec"),
        "_timed": attr.label(default = "//openroad:timed", executable = True, cfg = "exec"),
    },
)

def _sim_impl(ctx):
    log = ctx.actions.declare_file(ctx.label.name + ".log")
    includes = {f.dirname: True for f in ctx.files.srcs if f.extension == "svh"}
    period = ctx.file.period
    ctx.actions.run_shell(
        command = """
set -e
export IVL_BASE="$PWD/{base}"
{defines}
{iverilog} -g2012 -o {log}.vvp {includes} $DEFINES {srcs} > {log} 2>&1 || {{ cat {log}; exit 1; }}
{vvp} -M "$IVL_BASE" {log}.vvp >> {log} 2>&1
grep -q '^CA_SIM design=' {log} || {{ cat {log}; exit 1; }}
""".format(
            base = ctx.file._ivl_base.path,
            defines = 'DEFINES="-DPERIOD=$(cat {})"'.format(period.path) if period else 'DEFINES=""',
            iverilog = ctx.executable._iverilog.path,
            vvp = ctx.executable._vvp.path,
            log = log.path,
            includes = " ".join(["-I" + d for d in includes]),
            srcs = " ".join([f.path for f in ctx.files.srcs if f.extension != "svh"]),
        ),
        inputs = ctx.files.srcs + [ctx.file._ivl_base] + ([period] if period else []),
        tools = [ctx.attr._iverilog[DefaultInfo].files_to_run, ctx.attr._vvp[DefaultInfo].files_to_run],
        outputs = [log],
        mnemonic = "IcarusSim",
    )
    return [DefaultInfo(files = depset([log]))]

icarus_sim = rule(
    implementation = _sim_impl,
    doc = "Compile and run an Icarus simulation; the log carries a CA_SIM result line.",
    attrs = {
        "period": attr.label(allow_single_file = True, doc = "File with the clock period in ps, as PERIOD."),
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "_iverilog": attr.label(default = "@iverilog//:iverilog", executable = True, cfg = "exec"),
        "_ivl_base": attr.label(default = "@iverilog//:ivl_base", allow_single_file = True),
        "_vvp": attr.label(default = "@iverilog//:vvp", executable = True, cfg = "exec"),
    },
)

def _period_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".txt")
    script = ctx.actions.declare_file(ctx.label.name + ".tcl")

    def pick(name):
        found = [f for f in ctx.files.final if f.basename == name]
        if len(found) != 1:
            fail("{}: expected one {}".format(ctx.label, name))
        return found[0]

    netlist, spef, sdc = pick("6_final.v"), pick("6_final.spef"), pick("6_final.sdc")
    ctx.actions.write(script, "\n".join(
        ["read_liberty " + f.path for f in ctx.files.liberty] + [
            "read_verilog " + netlist.path,
            "link_design " + ctx.attr.top,
            "read_spef " + spef.path,
            "read_sdc " + sdc.path,
            "set_cmd_units -time ps",
            "set clk [lindex [all_clocks] 0]",
            "set period [get_property $clk period]",
            "set slack [sta::time_sta_ui [sta::worst_slack_cmd max]]",
            "set f [open " + out.path + " w]",
            "puts $f [format %.1f [expr {$period - $slack}]]",
            "close $f",
            "",
        ],
    ))
    ctx.actions.run(
        executable = ctx.executable._sta,
        arguments = ["-no_splash", "-exit", script.path],
        inputs = [netlist, spef, sdc, script] + ctx.files.liberty,
        outputs = [out],
        mnemonic = "MinimumPeriod",
    )
    return [DefaultInfo(files = depset([out]))]

minimum_period = rule(
    implementation = _period_impl,
    doc = "The minimum clock period a routed synchronous design reaches at a corner, in ps: period - worst slack.",
    attrs = {
        "final": attr.label(mandatory = True),
        "liberty": attr.label_list(allow_files = True, mandatory = True),
        "top": attr.string(mandatory = True),
        "_sta": attr.label(default = "@openroad//src/sta:opensta", executable = True, cfg = "exec"),
    },
)

def _idle_power_impl(ctx):
    out = ctx.actions.declare_file(ctx.label.name + ".json")
    script = ctx.actions.declare_file(ctx.label.name + ".tcl")

    def pick(name, required = True):
        found = [f for f in ctx.files.final if f.basename == name]
        if len(found) != 1 and required:
            fail("{}: expected one {}".format(ctx.label, name))
        return found[0] if found else None

    netlist, spef = pick("6_final.v"), pick("6_final.spef")
    sdc = pick("6_final.sdc") if ctx.attr.clocked else None
    ctx.actions.write(script, "\n".join(
        ["read_liberty " + f.path for f in ctx.files.liberty] + [
            "read_verilog " + netlist.path,
            "link_design " + ctx.attr.top,
            "read_spef " + spef.path,
        ] + (["read_sdc " + sdc.path] if sdc else []) + [
            # Waiting: no data input moves. A clock, if there is one, keeps running.
            "set_power_activity -input -density 0",
            "report_power -format json > " + out.path,
            "",
        ],
    ))
    ctx.actions.run(
        executable = ctx.executable._sta,
        arguments = ["-no_splash", "-exit", script.path],
        inputs = [netlist, spef, script] + ([sdc] if sdc else []) + ctx.files.liberty,
        outputs = [out],
        mnemonic = "IdlePower",
    )
    return [DefaultInfo(files = depset([out]))]

idle_power = rule(
    implementation = _idle_power_impl,
    doc = "report_power (W, JSON) of a routed design that is waiting: inputs still, clock (if any) running.",
    attrs = {
        "clocked": attr.bool(default = False),
        "final": attr.label(mandatory = True),
        "liberty": attr.label_list(allow_files = True, mandatory = True),
        "top": attr.string(mandatory = True),
        "_sta": attr.label(default = "@openroad//src/sta:opensta", executable = True, cfg = "exec"),
    },
)
