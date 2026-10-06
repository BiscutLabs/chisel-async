# SPDX-License-Identifier: Apache-2.0
"""CA-07 and mixed-encoding campaigns on emitted RTL with an external trace oracle."""
import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
import platform
import re
import subprocess
import sys

from run import ROOT, read_sources
from compare_controllers import random_words, sha
from phase_reference import replay
from phase_faults import FAULTS, run_fault
sys.path.insert(0, str(ROOT/'tools'))
from check_export import nodes, validate_export

FIXTURES = ('phase_to_four','phase_to_two','arbiter','two_buffer','two_wide','two_fifo','two_initialized',
            'two_initial','two_fork','two_join','two_select','two_merge','two_arbiter','two_transform',
            'encoding_to_dual','encoding_from_dual','encoding_roundtrip','phase_roundtrip')
INITIAL = (0x12,0x12,0xe7)
DIRECTED = {
    'immediate_source': 'two_buffer',
    'source_return_hold': 'phase_to_two',
    'reset_partial_valid': 'encoding_from_dual',
    'reset_partial_spacer': 'encoding_from_dual',
    'reset_partial_fork': 'two_fork',
    'reset_to_four_return': 'phase_to_four',
    'reset_to_two_return': 'phase_to_two',
    'reset_arbitration_handover': 'arbiter',
    'reset_arbitration_resolution': 'arbiter',
}


def flat(source):
    return source.split('>')[1].replace('.','_').replace('[','_').replace(']','')


def trace_channels(manifest):
    channels=list(manifest['design']['channels'])
    for node in list(nodes(manifest['design']))[1:]:
        channels += [dict(c,id=node['rtl_path'][len(manifest['top'])+1:]+'::'+c['id'],role='internal') for c in node['channels']]
    return channels


def payload(i, width, lane=0, tagged=False):
    if tagged: return (lane << 6) | ((i//2) % 31)
    mask=(1<<width)-1
    if i<2: return mask
    if i==2: return 0
    if i<3+width: return 1 << (i-3)
    if i<3+2*width: return mask ^ (1 << (i-3-width))
    return (37*i)&mask


def bench(fixture, manifest, ports, seed, overrides, scenario='standard'):
    design=manifest['design']; channels=design['channels']; endpoint={e['id']:e for e in design['endpoints']}
    inputs=[c for c in channels if c['role']=='input']; outputs=[c for c in channels if c['role']=='output']
    count=289 if fixture in ('encoding_to_dual','encoding_from_dual') else 135 if fixture=='two_wide' else 43
    widths={c['id']:sum(f['width'] for f in c['layout']) for c in channels}
    signals={}
    for c in channels:
        names={key:flat(endpoint[c[key]]['source']) for key in ('request','acknowledge','zero','one') if key in c}
        # Pack exactly the independent typed ABI order used by the exported layout.
        names['data']='{' + ','.join(flat(f['source']) for f in reversed(c['layout'])) + '}'
        signals[c['id']]=names
    def word(c,i):
        name=c['id']; width=widths[name]
        if fixture=='two_select':
            fields={f['field']:f for f in c['layout']}
            return (((i+i//3)%3)<<fields['bits.index']['lsb']) | (payload(i,8)<<fields['bits.data']['lsb'])
        if fixture in ('arbiter','two_arbiter','two_merge'):
            return payload(i,width,int(name[-1]),True)
        if fixture in ('encoding_from_dual','encoding_to_dual'): return (i//36) % 8
        return payload(i,width)
    deliveries=Counter()
    if fixture=='two_select':
        for i in range(count): deliveries[f'out{(i+i//3)%3}']+=1
    elif fixture=='two_fork': deliveries.update({c['id']:count for c in outputs})
    else: deliveries['out']=len(INITIAL) if fixture=='two_initial' else (2*count if fixture in ('arbiter','two_arbiter') else count)+(len(INITIAL) if fixture=='two_initialized' else 0)
    warm=Counter()
    if seed%2:
        if fixture=='two_fork': warm.update({c['id']:1 for c in outputs})
        elif fixture=='two_select': warm['out0']=1
        else: warm['out']=3 if fixture=='two_initialized' else 1
    lines=['module PhaseBench; timeunit 1fs; timeprecision 1fs;', 'integer trace;']
    for p in ports:
        name=flat(p['source']); init=" = 0" if p['direction']=='input' else ''
        lines.append(f"{'reg' if p['direction']=='input' else 'wire'} [{p['width']-1}:0] {name}{init};")
    lines.append(manifest['top']+' dut('+','.join('.'+flat(p['source'])+'('+flat(p['source'])+')' for p in ports)+');')
    lines+=overrides
    counters={}
    def count_completions(name, protocol, ack):
        counter=f'completed_{len(counters)}';counters[name]=counter
        edge='' if protocol=='two-phase-bundled-v1' else 'posedge '
        # Independent edge counters witness completeness of the settled trace.
        lines.extend([f'integer {counter}=0;',
                      f'always @({edge}{ack}) if (!reset) {counter}={counter}+1;'])
    for c in channels:
        name=c['id']; s=signals[name]; req=s.get('request',"1'b0"); zero=s.get('zero',"1'b0")
        lines.append(f'wire [{widths[name]-1}:0] observed_{name} = {s["data"]};')
        s['data']=f'observed_{name}'
        lines += [f'integer sent_{name}=0, received_{name}=0;',
          f'always @(reset or {req} or {s["acknowledge"]} or {s["data"]} or {zero})',
          f'  if (trace) $fstrobe(trace,"%0d|%0b|{name}|%0b|%0b|%0h|%0h",$time,reset,{req},{s["acknowledge"]},{s["data"]},{zero});']
        count_completions(name,c['protocol'],s['acknowledge'])
    # Observe registered child channel boundaries too: normalized bundled payloads
    # must obey full-return hold, even when a following latch would mask a violation.
    index=0
    for node in list(nodes(design))[1:]:
        endpoint_map={e['id']:e for e in node['endpoints']}
        prefix='dut'+node['rtl_path'][len(manifest['top']):]+'.'
        for c in node['channels']:
            index+=1
            name=node['rtl_path'][len(manifest['top'])+1:]+'::'+c['id']
            req=prefix+flat(endpoint_map[c['request']]['source']) if 'request' in c else "1'b0"
            ack=prefix+flat(endpoint_map[c['acknowledge']]['source'])
            zero=prefix+flat(endpoint_map[c['zero']]['source']) if 'zero' in c else "1'b0"
            data='{'+','.join(prefix+flat(f['source']) for f in reversed(c['layout']))+'}'
            width=sum(f['width'] for f in c['layout'])
            lines += [f'wire [{width-1}:0] internal_data_{index}={data};',
                      f'always @(reset or {req} or {ack} or {zero} or internal_data_{index})',
                      f'if (trace) $fstrobe(trace,"%0d|%0b|{name}|%0b|%0b|%0h|%0h",$time,reset,{req},{ack},internal_data_{index},{zero});']
            count_completions(name,c['protocol'],ack)
    lines += ['integer epoch=1;', 'task automatic snapshot; begin']
    for name,counter in counters.items():
        lines += [f'$fdisplay(trace,"COUNTS|%0d|{name}|%0d",epoch,{counter});',f'{counter}=0;']
    lines += ['epoch=epoch+1; end endtask']
    if fixture=='two_initial':
        source=next(c['contract'] for c in design['children'] if c['id']=='source')
        source_name=source['rtl_path'][len(manifest['top'])+1:]+'::out'
        source_prefix='dut'+source['rtl_path'][len(manifest['top']):]+'.'
        lines += ['reg done_seen=0;', 'always @(done or reset) begin',
                  'if (reset) done_seen=0;', 'else if (done) begin',
                  f'if ({counters[source_name]} != {len(INITIAL)} || {source_prefix}out_req || {source_prefix}out_ack) $fatal(1,"DONE_EARLY");',
                  'done_seen=1; end', 'else if (done_seen) $fatal(1,"DONE_WITHDRAWN"); end']
    permutations=list(itertools.permutations(range(3)))
    for c in inputs:
        name=c['id']; s=signals[name]; protocol=c['protocol']; width=widths[name]
        lines += [f'task automatic send_{name}(input [{width-1}:0] value, input integer item);', 'begin']
        if protocol=='dual-rail-rtz-v1':
            assert width==3
            lines.append('case (item % 6)')
            for i,order in enumerate(permutations):
                body=' '.join(f'#1000000; if (value[{bit}]) {s["one"]}[{bit}]=1; else {s["zero"]}[{bit}]=1;' for bit in order)
                lines.append(f'{i}: begin {body} end')
            lines += ['endcase',f'wait ({s["acknowledge"]}); #1;', 'case ((item / 6) % 6)']
            for i,order in enumerate(permutations):
                body=' '.join(f'#1000000; {s["one"]}[{bit}]=0; {s["zero"]}[{bit}]=0;' for bit in order)
                lines.append(f'{i}: begin {body} end')
            lines += ['endcase',f'wait (!{s["acknowledge"]}); #1;']
        else:
            for field in c['layout']:
                lines.append(f'{flat(field["source"])} = value[{field["lsb"]} +: {field["width"]}];')
            lines.append('#1000000;')
            if protocol=='two-phase-bundled-v1':
                response=0 if scenario=='immediate_source' else 1
                lines += [f'{s["request"]}=~{s["request"]}; wait ({s["acknowledge"]}=={s["request"]}); #{response};']
            else:
                hold=500000000 if scenario=='source_return_hold' else 1
                lines += [f'{s["request"]}=1; wait ({s["acknowledge"]}); #{hold}; {s["request"]}=0; wait (!{s["acknowledge"]}); #1;']
        lines += [f'sent_{name}=sent_{name}+1;', 'end endtask']
    for output_index, c in enumerate(outputs):
        name=c['id']; s=signals[name]; protocol=c['protocol']
        lines += [f'task automatic receive_{name}(input integer amount); integer k; begin', 'for(k=0;k<amount;k=k+1) begin']
        delay=f'#(1+1000000*((k+{seed}+{7*output_index})%19));'
        if protocol=='dual-rail-rtz-v1':
            lines += [f'wait (&({s["one"]}|{s["zero"]})); {delay} {s["acknowledge"]}=1;',
                      f'wait (({s["one"]}|{s["zero"]})==0); #1; {s["acknowledge"]}=0;']
        elif protocol=='two-phase-bundled-v1':
            lines += [f'wait ({s["request"]}!={s["acknowledge"]}); {delay} {s["acknowledge"]}={s["request"]};']
        else:
            lines += [f'wait ({s["request"]}); {delay} {s["acknowledge"]}=1;',
                      f'wait (!{s["request"]}); #(1+1000000*((k+{3*output_index})%7)); {s["acknowledge"]}=0;']
        lines += [f'#1; received_{name}=received_{name}+1; end end endtask']
    def stream(c,amount):
        gap=lambda i: '#0;' if scenario=='immediate_source' else f'#(1+{1000000*((i+seed)%11)});'
        return 'begin\n'+'\n'.join(f'send_{c["id"]}({widths[c["id"]]}\'h{word(c,i):x}, {i}); {gap(i)}' for i in range(amount))+'\nend'
    def sources(amount):
        if fixture=='two_merge':
            return ['begin\n'+'\n'.join(f'send_{inputs[i%3]["id"]}(8\'h{word(inputs[i%3],i):x}, {i}); #1;' for i in range(amount))+'\nend']
        return [stream(c,amount) for c in inputs]
    lines+=['task automatic clear_drivers; begin']
    for p in ports:
        if p['direction']=='input' and flat(p['source'])!='reset': lines.append(flat(p['source'])+'=0;')
    for c in channels: lines.append(f'sent_{c["id"]}=0; received_{c["id"]}=0;')
    lines+=['end endtask', 'task automatic run_stream; begin fork', *sources(count)]
    lines += [f'receive_{c["id"]}({deliveries[c["id"]]});' for c in outputs]
    lines += ['join #1000000000;']
    if fixture=='two_initial': lines.append('if (done !== 1) $fatal(1,"DONE_NOT_ASSERTED");')
    lines += ['end endtask', 'initial begin', 'trace=$fopen("trace.txt","w"); $fdisplay(trace,"PHASE_TRACE|2");',
              'reset=1; clear_drivers(); #1000000000; reset=0; #50000000; run_stream();',
              'snapshot(); reset=1; #1; clear_drivers(); #1000000000; reset=0; #50000000;']
    partial=scenario.startswith('reset_')
    middle=Counter()
    if warm and not partial:
        warm_inputs=[] if fixture in ('two_initial','two_initialized') else inputs[:1] if fixture in ('arbiter','two_arbiter','two_merge') else inputs
        lines += ['fork', *[stream(c,1) for c in warm_inputs],
                  *[f'receive_{c["id"]}({warm[c["id"]]});' for c in outputs], 'join #100000000;']
        lines += [f'sent_{c["id"]}=0;' for c in inputs]
    if partial:
        assert DIRECTED[scenario]==fixture, 'INVALID_DIRECTED_FIXTURE'
        traffic=sources(1)
        if scenario=='reset_partial_valid':
            traffic=['begin in_one=1; end']
            trigger='#5000000;';condition='in_one==1 && in_zero==0 && !in_ack && !out_req'
        elif scenario=='reset_partial_spacer':
            traffic=['begin in_one=7; wait(in_ack && received_out==1); in_one[0]=0; end','receive_out(1);']
            trigger='wait(in_one==6); #5000000;';condition='in_ack && in_one==6 && in_zero==0'
            middle['out']=1
        elif scenario=='reset_partial_fork':
            traffic+=['receive_out0(1);']
            trigger='wait(received_out0==1 && out_1_req!=out_1_ack && out_2_req!=out_2_ack);'
            condition='in_req!=in_ack && received_out1==0 && received_out2==0';middle['out0']=1
        elif scenario in ('reset_to_four_return','reset_to_two_return'):
            adapter=next(c['contract'] for c in design['children'] if c['id']=='adapter')
            prefix='dut'+adapter['rtl_path'][len(manifest['top']):]+'.'
            member='out' if scenario=='reset_to_four_return' else 'in'
            req,ack=prefix+member+'_req',prefix+member+'_ack'
            trigger=f'wait({ack}); wait(!{req});';condition=f'!{req} && {ack}'
            if scenario=='reset_to_two_return': traffic+=['receive_out(1);'];middle['out']=1
        else:
            mutex=next(p for p in design['primitives'] if p['model']=='ChiselAsyncMutex_v1')
            grant='dut'+mutex['rtl_path'][len(manifest['top']):]+'.grant'
            if scenario=='reset_arbitration_handover':
                trigger=f'wait(in_0_ack); wait(!in_0_req); wait({grant}==0);'
                condition=f'{grant}==0 && in_0_ack && in_1_req && !in_1_ack'
            else:
                trigger='wait(in_0_req && in_1_req);';condition=f'{grant}==0 && !in_0_ack && !in_1_ack'
        # Only the observed-state branch may finish. A completed source/sink
        # cannot win join_any and accidentally turn this into a quiescent reset.
        lines += ['fork : held', *['begin '+t+' wait(1\'b0); end' for t in traffic],
                  f'begin {trigger} #1; if (!({condition})) $fatal(1,"RESET_SCENARIO_NOT_REACHED");',
                  f'$display("SCENARIO_REACHED:{scenario}"); end', 'join_any']
    else:
        lines += ['fork : held', *sources((design['capacity'] or 2)+3), 'begin #5000000000; end', 'join_any']
        if inputs:
            capacity=0 if fixture=='two_fork' or fixture=='two_initialized' and not warm else 2 if fixture=='two_join' else design['capacity'] or 1
            lines.append('if ('+'+'.join(f'sent_{c["id"]}' for c in inputs)+f' != {capacity}) $fatal(1,"CAPACITY_MISMATCH");')
    if fixture=='two_initial': lines.append('if (done !== 0) $fatal(1,"DONE_EARLY");')
    lines += ['snapshot(); reset=1; disable held; #1; clear_drivers(); #1000000000; reset=0; #50000000; run_stream();',
              'snapshot();',
              '$fclose(trace); trace=0; $display("PHASE_PASS"); $finish; end',
              'initial begin #1000000000000; $fatal(1,"PROGRESS_DEADLINE"); end', 'endmodule']
    text='\n'.join(lines)+'\n'
    if fixture=='two_initial':
        text=text.replace('#1000000000; reset=0;', '#1000000000; if (done !== 0) $fatal(1,"DONE_RESET"); reset=0;')
    return text, {k:2*v+(middle[k] if partial else warm[k]) for k,v in deliveries.items()}


def delay_overrides(manifest, seed):
    if seed==0: return []
    rng=random_words(seed+1); result=[]; top=manifest['top']
    for node in nodes(manifest['design']):
        policy=next((t for t in node['timing'] if t['kind']=='long-hold-bundling-v2'),None)
        adapter=next((t for t in node['timing'] if t['kind'] in ('phase-conversion-v1','encoding-boundary-v1')),None)
        for p in node['primitives']:
            key='RESOLVE_FS' if p['model']=='ChiselAsyncMutex_v1' else 'DELAY_FS'
            if key not in p['parameters'] or p['id'] in ('request_delay','output_delay','return_guard','acknowledge_guard','decoded_request_guard'): continue
            delay=1000000*(1 if seed==1 else 10 if seed==2 else 1+next(rng)%10)
            bounds=adapter['cells'] if adapter else None
            if policy:
                bounds={**policy['control_delays'],'payload':policy['latch_delay'],'data_delay':policy['data_delay']}.get(p['id'])
            if bounds: assert int(bounds['min_fs'])<=delay<=int(bounds['max_fs']), 'OVERRIDE_OUTSIDE_POLICY'
            result.append(f'defparam dut{p["rtl_path"][len(top):]}.{key}={delay};')
    return result


def execute(fixture, seed, directory, manifest, ports, sources, scenario='standard'):
    directory.mkdir(parents=True,exist_ok=True)
    overrides=delay_overrides(manifest,seed)
    # Explore both legal collision outcomes and an alternating digital policy.
    for node in nodes(manifest['design']):
        for p in node['primitives']:
            if p['model']=='ChiselAsyncMutex_v1': overrides.append(f'defparam dut{p["rtl_path"][len(manifest["top"]):]}.POLICY={seed%3};')
    text,expected=bench(fixture,manifest,ports,seed,overrides,scenario)
    path=directory/'bench.sv';path.write_text(text,encoding='utf-8')
    command=['iverilog','-g2012','-s','PhaseBench','-o',str(directory/'sim.vvp'),str(path),*map(str,sources)]
    compile_result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (directory/'compile.log').write_text(compile_result.stdout+compile_result.stderr,encoding='utf-8')
    assert compile_result.returncode==0, 'PHASE_COMPILE: '+compile_result.stderr
    result=subprocess.run(['vvp',str(directory/'sim.vvp')],cwd=directory,capture_output=True,text=True,timeout=30)
    log=result.stdout+result.stderr;(directory/'simulation.log').write_text(log,encoding='utf-8')
    assert result.returncode==0 and log.splitlines().count('PHASE_PASS')==1, 'PHASE_SIMULATION: '+log
    if scenario.startswith('reset_'):
        assert log.splitlines().count('SCENARIO_REACHED:'+scenario)==1, 'RESET_SCENARIO_ACTIVITY'
    require_abort=scenario not in ('reset_partial_valid','reset_partial_spacer','reset_to_two_return')
    evidence=replay(fixture,trace_channels(manifest),directory/'trace.txt',require_abort=require_abort)
    assert evidence['deliveries']==expected, 'PHASE_ACTIVITY'
    case=dict(fixture=fixture,seed=seed,scenario=scenario,status='PASS',evidence=evidence,overrides=overrides,
              compile=command,bench_sha256=sha(path),trace_sha256=sha(directory/'trace.txt'),log_sha256=sha(directory/'simulation.log'))
    (directory/'case.json').write_text(json.dumps(case,indent=2)+'\n',encoding='utf-8')
    return case


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'target/generated')
    parser.add_argument('--output',type=Path,default=ROOT/'target/verification/phase')
    parser.add_argument('--fixtures',nargs='+',choices=FIXTURES,default=list(FIXTURES))
    parser.add_argument('--seeds',nargs='+',type=int,default=list(range(303)))
    parser.add_argument('--faults-only',action='store_true')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    record=dict(status='RUNNING',trace_schema='chisel-async-phase-trace-v2',platform=platform.platform(),python=sys.version,cases=[],directed=[],faults=[],exports={},sources={},
                checker_sha256={p.name:sha(p) for p in (Path(__file__),ROOT/'verification/phase_reference.py',ROOT/'verification/phase_faults.py',
                    ROOT/'verification/compare_controllers.py',ROOT/'verification/run.py',ROOT/'tools/check_export.py')})
    def save(): (out/'report.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        assert args.fixtures and args.seeds and len(set(args.fixtures))==len(args.fixtures) and len(set(args.seeds))==len(args.seeds), 'INVALID_CASE_SELECTION'
        assert all(0<=s<2**32 for s in args.seeds), 'INVALID_PHASE_SEED'
        version=subprocess.run(['iverilog','-V'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
        assert 'version 13.0 ' in version, 'UNQUALIFIED_PHASE_SIMULATOR'
        record['simulator']=version
        record['selected']=[] if args.faults_only else [f'{f}_{s}' for f in args.fixtures for s in args.seeds]
        record['required_faults']=[name for name,(fixture,_) in FAULTS.items() if fixture in args.fixtures];save()
        record['required_directed']=[] if args.faults_only else [f'{name}_{seed}' for name,f in DIRECTED.items()
                                                               if f in args.fixtures for seed in (0,2)]
        assert record['selected'] or record['required_faults'], 'EMPTY_PHASE_CAMPAIGN'
        for fixture in args.fixtures:
            generated=args.generated.resolve()/fixture
            record['exports'][fixture]=validate_export(generated)
            manifest=json.loads((generated/'contract.json').read_text(encoding='utf-8'))['manifest']
            ports=json.loads((generated/'ports.json').read_text(encoding='utf-8'))['nodes'][0]['ports']
            dest=out/'sources'/fixture;dest.mkdir(parents=True,exist_ok=True)
            sources=[]
            for original in read_sources(generated):
                path=dest/original.name;path.write_bytes(original.read_bytes());sources.append(path)
            record['sources'][fixture]={p.name:sha(p) for p in sources}
            for seed in ([] if args.faults_only else args.seeds):
                record['cases'].append(execute(fixture,seed,out/f'{fixture}_{seed}',manifest,ports,sources))
            for name in ([] if args.faults_only else DIRECTED):
                if DIRECTED[name]==fixture:
                    for seed in (0,2):
                        record['directed'].append(execute(fixture,seed,out/'directed'/f'{name}_{seed}',manifest,ports,sources,name))
            for name in record['required_faults']:
                if FAULTS[name][0]==fixture:
                    record['faults'].append(run_fault(name,manifest,ports,sources,out/'faults'/name,bench,trace_channels))
            save();print(f'{fixture}: {0 if args.faults_only else len(args.seeds)} cases and paired controls PASS',flush=True)
        assert len(record['cases'])==len(record['selected']), 'INCOMPLETE_PHASE_CAMPAIGN'
        assert len(record['faults'])==len(record['required_faults']), 'INCOMPLETE_FAULT_CAMPAIGN'
        assert len(record['directed'])==len(record['required_directed']), 'INCOMPLETE_DIRECTED_CAMPAIGN'
        record['status']='PASS'
    except BaseException as error:
        record.update(status='ERROR',error=str(error));save();raise
    save();print(f'Phase campaign PASS: {len(record["cases"])} cases',flush=True)


if __name__=='__main__': main()
