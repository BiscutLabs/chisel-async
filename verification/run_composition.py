# SPDX-License-Identifier: Apache-2.0
"""Native CA-06 behavioral campaign, raw traces, exact faults and source identities."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from run import ROOT, read_sources
from composition_reference import replay
sys.path.insert(0,str(ROOT/'tools'))
from check_export import validate_export, nodes

FIXTURES = dict(fifo_one='FifoOneExample',fifo='FifoExample',initialized_fifo='InitializedFifoExample',
                initial_tokens='InitialTokensExample',fork='ForkExample',join='JoinExample',select='SelectExample',
                merge='MergeExample',fork_join='ForkJoinExample',feedback='FeedbackExample',initial_wide='InitialWideExample')
FAULTS = {
    'fifo_overaccept': ('fifo','CAPACITY_EXCEEDED'),
    'fork_early_accept': ('fork','FORK_EARLY_ACCEPT'),
    'fork_early_return': ('fork','FORK_EARLY_RETURN'),
    'join_wrong_operand': ('join','JOIN_PAIR'),
    'select_wrong_branch': ('select','SELECT_ROUTE'),
    'select_live_data': ('select','COMPOSITION_DATA_HOLD'),
    'initial_payload': ('initialized_fifo','PAYLOAD_MISMATCH'),
    'merge_contention': ('merge','EXCLUSIVE_MERGE_CONTENTION'),
    'merge_contention_return': ('merge','EXCLUSIVE_MERGE_CONTENTION'),
    'invalid_select': ('select','SELECT_INDEX_OUT_OF_RANGE'),
}
DELIVERIES = {'fifo_one':92,'fifo':94,'initialized_fifo':106,'initial_tokens':14,'fork':374,'join':92,'select':91,'initial_wide':18}


def mutate(text, scenario):
    replacements = {
        'fifo_overaccept': [('in_ack', "in_req", 1000000)],
        'fork_early_accept': [('in_ack','out_0_ack',0)],
        'fork_early_return': [('in_ack','out_0_ack & out_1_ack & out_2_ack',0)],
        'join_wrong_operand': [('out_bits_right','out_bits_left',0)],
        'select_live_data': [('out_1_bits','in_bits_data',0)],
    }
    if scenario=='select_wrong_branch':
        values=[re.findall(rf'assign out_{i}_req = ([^;]+);',text) for i in (0,1)]
        assert all(len(v)==1 for v in values), 'MUTATION_TARGET'
        replacements[scenario]=[('out_0_req',values[1][0],0),('out_1_req',values[0][0],0)]
    if scenario=='initial_payload':
        values=re.findall(r'assign out_bits = ([^;]+);',text)
        assert len(values)==1, 'MUTATION_TARGET'
        replacements[scenario]=[('out_bits',f'~({values[0]})',0)]
    for port,value,delay in replacements.get(scenario,[]):
        text,count=re.subn(rf'assign {port} = [^;]+;',f'assign #{delay}fs {port} = {value};',text)
        assert count==1, 'MUTATION_TARGET'
    return text


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def worker(fixture, seed, output, generated, scenario):
    from cocotb_tools.runner import get_runner
    output.mkdir(parents=True,exist_ok=True)
    resolution=validate_export(generated/fixture)
    sources=read_sources(generated/fixture)
    build=output/'build'; build.mkdir(exist_ok=True)
    compiled=[]
    for original in sources:
        dest=build/original.name
        text=original.read_text(encoding='utf-8')
        if original.name==FIXTURES[fixture]+'.sv': text=mutate(text,scenario)
        dest.write_text(text,encoding='utf-8'); compiled.append(dest)
    # Positive per-instance delay overrides are recorded and constrained by each
    # long-hold envelope. Composition cells are a separate 1..10 ns experiment.
    overrides=[]
    if seed:
        manifest=json.loads((generated/fixture/'contract.json').read_text())['manifest']
        state=seed
        for node in nodes(manifest['design']):
            bounds={}
            for policy in node['timing']:
                if policy['kind']=='long-hold-bundling-v2':
                    bounds={**policy['control_delays'],'data_delay':policy['data_delay'],'payload':policy['latch_delay']}
            for p in node['primitives']:
                if 'DELAY_FS' not in p['parameters'] or p['id'] in ('request_delay','output_delay'): continue
                state=(1664525*state+1013904223)&0xffffffff
                delay=1 if seed==1 else 10 if seed==2 else 1+state%10
                if p['id'] in bounds:
                    bound=bounds[p['id']]
                    assert int(bound['min_fs'])<=delay*1000000<=int(bound['max_fs']), 'COMPOSITION_DELAY_OUTSIDE_STAGE_BOUNDS'
                # The seed source data delay stays within the same declared 1..10 ns bound.
                overrides.append(f"defparam {p['rtl_path']}.DELAY_FS={delay*1000000};")
        overlay=build/'delays.sv'
        overlay.write_text('module CompositionOverrides;\n'+'\n'.join(overrides)+'\nendmodule\n',encoding='utf-8')
        compiled.append(overlay)
    runner=get_runner('icarus')
    runner.build(sources=compiled,hdl_toplevel=FIXTURES[fixture],build_dir=build,
                 build_args=['-s','CompositionOverrides'] if seed else [],
                 always=True,timescale=('1ns','1fs'),log_file=output/'build.log')
    sys.path.insert(0,str(ROOT/'verification/cocotb'))
    sys.path.insert(0,str(ROOT/'verification'))
    xml=output/'results.xml'
    for stale in (xml,output/'evidence.json',output/'trace.jsonl',output/'case.json'):
        stale.write_text('',encoding='utf-8')
    simulation_error=None
    try:
        runner.test(hdl_toplevel=FIXTURES[fixture],test_module='composition_sim',
            extra_env={'COMPOSITION_FIXTURE':fixture,'COMPOSITION_SEED':str(seed),'COMPOSITION_SCENARIO':scenario,
                       'COMPOSITION_OUTPUT':str(output)},seed=8675309,
            results_xml=str(xml),log_file=output/'simulation.log')
    except RuntimeError as error:
        simulation_error=str(error)
    cases=list(ET.parse(xml).iter('testcase'))
    assert len(cases)==1 and cases[0].get('name')=='composition_contract', 'COMPOSITION_TEST_INVENTORY'
    log=(output/'simulation.log').read_text(encoding='utf-8')
    if scenario in FAULTS:
        diagnostic=FAULTS[scenario][1]
        assert not cases[0].findall('skipped') and (cases[0].findall('failure') or cases[0].findall('error')), 'FAULT_NOT_ACTIVATED'
        if diagnostic in ('EXCLUSIVE_MERGE_CONTENTION','SELECT_INDEX_OUT_OF_RANGE'):
            assert simulation_error and re.findall(r'^FATAL: [^\n]*?: (\w+)',log,re.M)==[diagnostic], 'WRONG_GUARD_REJECTION'
        else:
            assert simulation_error is None, 'UNRELATED_SIMULATION_FAILURE'
            evidence=json.loads((output/'evidence.json').read_text())
            assert evidence['status']=='FAIL' and evidence['diagnostic']==diagnostic, evidence
            events=[json.loads(x) for x in (output/'trace.jsonl').read_text().splitlines()]
            # The retained raw trace must independently activate the same checker.
            try: replay(fixture,port_roles(generated/fixture),events)
            except AssertionError as error: assert str(error)==diagnostic, 'WRONG_TRACE_REJECTION'
            else: raise AssertionError('TRACE_FAULT_NOT_ACTIVATED')
        (output/'case.json').write_text(json.dumps(dict(status='EXPECTED_REJECTION',fixture=fixture,
            scenario=scenario,diagnostic=diagnostic,sources={p.name:sha(p) for p in compiled},
            trace_sha256=sha(output/'trace.jsonl'),log_sha256=sha(output/'simulation.log')),indent=2)+'\n',encoding='utf-8')
        return
    assert simulation_error is None, simulation_error
    assert not cases[0].findall('skipped') and not cases[0].findall('failure') and not cases[0].findall('error'), (output/'simulation.log').read_text()[-6000:]
    evidence=json.loads((output/'evidence.json').read_text())
    assert evidence['status']=='PASS', evidence
    assert evidence['delivered']==DELIVERIES.get(fixture,90), 'COMPOSITION_ACTIVITY'
    assert evidence['resets']==(9 if fixture in ('fifo_one','fifo','initialized_fifo') else 7), 'COMPOSITION_RESET_INVENTORY'
    events=[json.loads(x) for x in (output/'trace.jsonl').read_text().splitlines()]
    # Root ports reconstructed from typed manifest, not guessed from the driver.
    summary=replay(fixture,port_roles(generated/fixture),events)
    assert all(evidence[k]==v for k,v in summary.items()), 'COMPOSITION_TRACE_SUMMARY'
    record=dict(status='PASS',fixture=fixture,seed=seed,scenario=scenario,resolution=resolution,
                evidence=evidence,trace_sha256=sha(output/'trace.jsonl'),xml_sha256=sha(Path(xml)),
                sources={p.name:sha(p) for p in compiled},overrides=overrides)
    (output/'case.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')


def port_roles(directory):
    design=json.loads((directory/'contract.json').read_text())['manifest']['design']
    endpoints={e['id']:e for e in design['endpoints']}
    return {endpoints[c['request']]['source'].split('>')[1][:-4].replace('.','_').replace('[','_').replace(']',''):c['role']
            for c in design['channels']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'target/generated')
    parser.add_argument('--output',type=Path,default=ROOT/'target/verification/composition')
    parser.add_argument('--fixtures',nargs='+',choices=FIXTURES,default=list(FIXTURES))
    parser.add_argument('--seeds',nargs='+',type=int,default=[0,1,2,17,29,43])
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--scenario',choices=['normal',*FAULTS],default='normal')
    parser.add_argument('--faults-only',action='store_true')
    args=parser.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    if args.worker:
        assert len(args.fixtures)==len(args.seeds)==1, 'WORKER_SELECTION'
        assert args.scenario=='normal' or FAULTS[args.scenario][0]==args.fixtures[0], 'FAULT_FIXTURE'
        worker(args.fixtures[0],args.seeds[0],out,args.generated.resolve(),args.scenario); return
    record=dict(status='RUNNING',platform=platform.platform(),python=sys.version,cases=[],
        checker_sha256={p.name:sha(p) for p in (Path(__file__),ROOT/'verification/composition_reference.py',
                                              ROOT/'verification/cocotb/composition_sim.py')})
    def save(): (out/'report.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        version=subprocess.run(['iverilog','-V'],capture_output=True,text=True,check=True).stdout.splitlines()[0]
        assert 'version 13.0 ' in version, 'UNQUALIFIED_COMPOSITION_SIMULATOR'
        record['simulator']=version
        record['routing_delay_experiment']={'min_fs':1000000,'max_fs':10000000,
            'scope':'recorded per-instance overrides of nominal routing/initialization cells; ideal wires, atomic cells',
            'stage_policy':'each long-hold override must also fit its exported per-role bounds'}
        assert all(0<=seed<=0xffffffff for seed in args.seeds), 'INVALID_COMPOSITION_SEED'
        assert len(set(args.fixtures))==len(args.fixtures) and len(set(args.seeds))==len(args.seeds), 'DUPLICATE_COMPOSITION_CASE'
        selected=[] if args.faults_only else [(f,seed,'normal') for f in args.fixtures for seed in args.seeds]
        selected += [(f,0,name) for name,(f,_) in FAULTS.items() if f in args.fixtures]
        record['selected']=[f'{f}_{seed}_{scenario}' for f,seed,scenario in selected]; save()
        for f,seed,scenario in selected:
            dest=out/f'{f}_{seed}_{scenario}'
            command=[sys.executable,str(Path(__file__).resolve()),'--worker','--fixtures',f,'--seeds',str(seed),
                     '--generated',str(args.generated.resolve()),'--output',str(dest),'--scenario',scenario]
            subprocess.run(command,check=True,timeout=120)
            case=json.loads((dest/'case.json').read_text()); case['command']=command
            assert case['status']==('PASS' if scenario=='normal' else 'EXPECTED_REJECTION'), 'INCOMPLETE_COMPOSITION_CASE'
            record['cases'].append(case); save(); print(f'{f}_{seed}_{scenario}: {case["status"]}',flush=True)
        assert record['cases'] and len(record['cases'])==len(selected), 'EMPTY_OR_PARTIAL_COMPOSITION_CAMPAIGN'
        record['status']='PASS'
    except BaseException as error:
        record.update(status='ERROR',error=str(error)); save(); raise
    save()


if __name__=='__main__': main()
