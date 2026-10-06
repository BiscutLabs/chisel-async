# SPDX-License-Identifier: Apache-2.0
"""Paired finite-prefix controls. Mutate real DUT source/parameters, never the oracle.

Every baseline completes real traffic. A fault must activate its exact trace or
protocol-guard diagnostic; host failures and the progress watchdog never count.
"""
import json
import re
import subprocess
from compare_controllers import sha
from phase_reference import replay

FAULTS = {
 'early_ack':('two_buffer','TWO_PHASE_ORDER'),
 'level_request':('phase_to_two','FOUR_PHASE_ORDER'),
 'reset_parity':('phase_to_two','UNEXPECTED_TOKEN'),
 'short_return_guard':('phase_to_four','FOUR_PHASE_ORDER'),
 'both_grants':('arbiter','EXCLUSIVE_MERGE_CONTENTION'),
 'missing_interlock':('arbiter','EXCLUSIVE_MERGE_CONTENTION'),
 'merge_early_release':('arbiter','DATA_HOLD'),
 'wrong_route':('two_select','UNEXPECTED_TOKEN'),
 'overlapping_rails':('encoding_to_dual','INVALID_RAIL'),
 'stateless_completion':('encoding_from_dual','RAIL_EARLY_SPACER'),
 'decoded_data_leak':('encoding_from_dual','DATA_HOLD'),
 'early_decoded_request':('encoding_from_dual','DATA_HOLD'),
 'done_stuck_low':('two_initial','DONE_NOT_ASSERTED'),
 'done_early':('two_initial','DONE_EARLY'),
 'done_withdrawn':('two_initial','DONE_WITHDRAWN'),
 'done_reset':('two_initial','DONE_RESET'),
}


def replace_once(text, before, after):
    assert text.count(before)==1, 'FAULT_TARGET_COUNT'
    return text.replace(before,after)


def bypass_pin(text, instance, expression, width, delay=0):
    pattern=r'('+re.escape(instance)+r'\s*\([\s\S]*?\.q\s*\()([A-Za-z_][A-Za-z0-9_]*)(\))'
    match=re.search(pattern,text)
    assert match, 'FAULT_PIN_TARGET'
    original=match[2]
    changed=re.sub(pattern,lambda m:m[1]+'unused_fault_q'+m[3],text,count=1)
    changed=changed.replace(');',f');\ntimeunit 1fs; timeprecision 1fs;\nwire [{width-1}:0] unused_fault_q;',1)
    return changed.replace('endmodule',f'assign #{delay} {original} = reset ? 0 : {expression};\nendmodule')


def run_fault(name, manifest, ports, sources, directory, make_bench, channel_list):
    fixture,diagnostic=FAULTS[name]
    text,_=make_bench(fixture,manifest,ports,0,[])
    text=replace_once(text,'initial begin #1000000000000; $fatal(1,"PROGRESS_DEADLINE"); end',
                      'initial begin #4000000000; $display("FAULT_PREFIX_COMPLETE"); $finish; end')
    if name in ('stateless_completion','decoded_data_leak','early_decoded_request'):
        assert text.count("send_in(3'h0, 0)")==2, 'FAULT_DRIVER_TARGET'
        text=text.replace("send_in(3'h0, 0)","send_in(3'h7, 0)",1)
    if name=='stateless_completion':
        # Widen partial rail return beyond the declared request/ack guards.
        text=text.replace('#1000000; in_one[','#200000000; in_one[')
    originals={p.name:p.read_text(encoding='utf-8') for p in sources}
    changed=dict(originals)
    top=manifest['top']+'.sv'
    overrides=[];baseline_overrides=[]
    if name=='early_ack':
        changed[top],n=re.subn(r'assign in_ack = [^;]+;', 'assign in_ack = in_req;',changed[top]);assert n==1
    elif name=='level_request':
        key='ChiselAsyncToggle_v1.sv';changed[key]=replace_once(changed[key],'assign #DELAY_FS q = phase;',"assign #DELAY_FS q = reset ? 1'b0 : trigger;")
    elif name=='reset_parity':
        key='ChiselAsyncToggle_v1.sv';changed[key]=replace_once(changed[key],"if (reset) phase <= 1'b0;","if (reset) phase <= 1'b1;")
    elif name=='short_return_guard':
        adapter=next(c['contract'] for c in manifest['design']['children'] if c['id']=='adapter')
        for p in adapter['primitives']:
            if p['id'] in ('return_guard','master_close','phase'):
                delay={'return_guard':0,'master_close':10000000,'phase':5000000}[p['id']]
                path=f'dut{p["rtl_path"][len(manifest["top"]):]}.DELAY_FS'
                overrides.append(f'defparam {path}={delay};')
                baseline_overrides.append(f'defparam {path}={p["parameters"]["DELAY_FS"] if p["id"]=="return_guard" else delay};')
    elif name=='early_decoded_request':
        for p in manifest['design']['primitives']:
            if p['id'] in ('decoded_request_guard','decoded'):
                delay=0 if p['id']=='decoded_request_guard' else 10000000
                path=f'dut{p["rtl_path"][len(manifest["top"]):]}.DELAY_FS'
                overrides.append(f'defparam {path}={delay};')
                baseline_overrides.append(f'defparam {path}={p["parameters"]["DELAY_FS"] if p["id"]=="decoded_request_guard" else delay};')
    elif name.startswith('done_'):
        changed[top],n=re.subn(r'\.done\s*\(done\)', '.done (original_done)', changed[top]);assert n==1, 'FAULT_DONE_TARGET'
        behavior={
            'done_stuck_low': "assign done = 1'b0;",
            'done_early': 'assign done = !reset;',
            'done_withdrawn': 'reg withdrawn=0; always @(posedge reset) withdrawn=0; '
                              'always @(posedge original_done) #1000000 withdrawn=1; assign done=original_done && !withdrawn;',
            'done_reset': 'reg stale_done=0; always @(posedge original_done) stale_done=1; assign done=stale_done;',
        }[name]
        changed[top]=changed[top].replace(');',');\ntimeunit 1fs; timeprecision 1fs;\nwire original_done;',1)
        changed[top]=changed[top].replace('endmodule',f'{behavior}\nendmodule')
    elif name=='both_grants':
        key='ChiselAsyncMutex_v1.sv';changed[key]=replace_once(changed[key],'assign #RESOLVE_FS grant = desired;', 'assign #RESOLVE_FS grant = reset ? 0 : request;')
    elif name=='missing_interlock':
        key='ChiselAsyncAnd_v1.sv';changed[key]=replace_once(changed[key],'&(d ^ INVERT)','d[0]')
    elif name=='merge_early_release':
        key='FourPhaseMerge.sv';changed[key],n=re.subn(r'(in_[01]_req) \| packed_\d+(?= \?)',r'\1',changed[key]);assert n==2
    elif name=='wrong_route':
        a=re.search(r'assign out_0_req = ([^;]+);',changed[top]);b=re.search(r'assign out_1_req = ([^;]+);',changed[top]);assert a and b
        changed[top]=changed[top].replace(a[0],f'assign out_0_req = {b[1]};').replace(b[0],f'assign out_1_req = {a[1]};')
    elif name=='overlapping_rails':
        key='ChiselAsyncAnd_v1.sv';changed[key]=replace_once(changed[key],'&(d ^ INVERT)',"&(d ^ 2'b10)")
    elif name in ('stateless_completion','decoded_data_leak'):
        identity='completion' if name=='stateless_completion' else 'decoded'
        p=next(p for p in manifest['design']['primitives'] if p['id']==identity)
        changed[top]=bypass_pin(changed[top],p['rtl_path'].split('.')[-1],
                               '&(in_one | in_zero)' if identity=='completion' else 'in_one',1 if identity=='completion' else 3,
                               2000000 if identity=='completion' else 0)
    else: raise AssertionError('UNKNOWN_FAULT')
    assert changed!=originals or overrides, 'FAULT_NOT_APPLIED'
    outcomes=[]
    for mutant in (False,True):
        out=directory/('fault' if mutant else 'baseline');out.mkdir(parents=True,exist_ok=True)
        selected_overrides=overrides if mutant else baseline_overrides
        path=out/'bench.sv';path.write_text(text.replace('endmodule','\n'.join(selected_overrides)+'\nendmodule'),encoding='utf-8')
        compiled=[]
        for filename,body in (changed if mutant else originals).items():
            p=out/filename;p.write_text(body,encoding='utf-8');compiled.append(p)
        command=['iverilog','-g2012','-s','PhaseBench','-o',str(out/'sim.vvp'),str(path),*map(str,compiled)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        (out/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        assert result.returncode==0, 'FAULT_COMPILE: '+result.stderr
        result=subprocess.run(['vvp',str(out/'sim.vvp')],cwd=out,capture_output=True,text=True,timeout=30)
        log=result.stdout+result.stderr;(out/'simulation.log').write_text(log,encoding='utf-8')
        fatals=re.findall(r'^FATAL: [^\n]*?: (\w+)',log,re.M)
        guard_diagnostic=diagnostic=='EXCLUSIVE_MERGE_CONTENTION' or diagnostic.startswith('DONE_')
        if mutant and guard_diagnostic:
            assert result.returncode==1 and fatals==[diagnostic], 'WRONG_GUARD_REJECTION: '+log
        else:
            assert result.returncode==0 and not fatals and log.splitlines().count('FAULT_PREFIX_COMPLETE')==1, 'FAULT_PREFIX_FAILURE: '+log
        observed=None;activity=None
        try:
            ledger=replay(fixture,channel_list(manifest),out/'trace.txt',complete=False)
            activity=sum(ledger.stats['deliveries'].values())
        except AssertionError as error:
            observed=str(error)
            (out/'diagnostic.txt').write_text(str(error)+'\n'+'\n'.join(getattr(error,'__notes__',[])),encoding='utf-8')
        if not mutant:
            assert observed is None and activity and activity>0, f'FAULT_BASELINE:{name}:{observed}'
        elif not guard_diagnostic:
            assert observed==diagnostic, f'WRONG_TRACE_REJECTION:{name}:{observed} expected {diagnostic}'
        outcomes.append(dict(status='EXPECTED_REJECTION' if mutant else 'PASS',diagnostic=diagnostic if mutant else None,
            deliveries=activity,compile=command,sources={p.name:sha(p) for p in compiled},bench_sha256=sha(path),
            trace_sha256=sha(out/'trace.txt'),log_sha256=sha(out/'simulation.log')))
        (out/'report.json').write_text(json.dumps(outcomes[-1],indent=2)+'\n',encoding='utf-8')
    return dict(name=name,fixture=fixture,status='PASS',diagnostic=diagnostic,outcomes=outcomes)
