# SPDX-License-Identifier: Apache-2.0
"""Same exhaustive small arithmetic task across behavioral, bundled, DIMS and GALS RTL.

Latencies include adapters, storage and clocks. These digital model numbers are
not silicon performance/area/power estimates. Epoch one is single-flight; epoch
three stresses capacity/backpressure. Epoch two deliberately aborts stalled work.
"""
import argparse
from collections import Counter, deque
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess

from run import ROOT, read_sources
from run_phase import flat, nodes, delay_overrides
from phase_reference import Protocol
from compare_controllers import random_words, sha
from check_export import validate_export
from campaign_environment import identity

STYLES = ('behavioral', 'bundled', 'qdi', 'gals')


def bench(style, manifest, ports, seed):
    rng = random_words(seed+17)
    # Complete input space, repeats/carry boundaries, then independent pseudo-random traffic.
    words = list(range(16))*2 + [0, 15, 15, 0]*4 + [next(rng)%16 for _ in range(48)]
    count = len(words); cap = manifest['design']['capacity']
    lines = ['module ReferenceBench; timeunit 1fs; timeprecision 1fs;',
             'integer log, epoch=0, delivered=0, accepted=0; reg serial=0;']
    for p in ports:
        lines.append(f'{"reg" if p["direction"]=="input" else "wire"} [{p["width"]-1}:0] {flat(p["source"])}' + ('=0;' if p['direction']=='input' else ';'))
    lines.append(manifest['top']+' dut('+','.join('.'+flat(p['source'])+'('+flat(p['source'])+')' for p in ports)+');')
    lines += delay_overrides(manifest, seed)
    clocks = None
    if style == 'gals':
        clocks = [7000000+seed%5*1000000, 11000000+seed%7*1000000, 3000000+seed%3*1000000]
        lines += [f'always #{clocks[0]} sourceClock=~sourceClock;',
                  f'initial begin #{clocks[2]}; forever #{clocks[1]} sinkClock=~sinkClock; end']
    channels = []; idle_terms=[]
    for node in nodes(manifest['design']):
        ends = {e['id']:e for e in node['endpoints']}; prefix='dut'+node['rtl_path'][len(manifest['top']):]+'.'
        for c in node['channels']:
            name = node['rtl_path']+'::'+c['id']; idx=len(channels)
            width=sum(f['width'] for f in c['layout'])
            def signal(key): return prefix+flat(ends[c[key]]['source'])
            data='{'+','.join(prefix+flat(f['source']) for f in reversed(c['layout']))+'}'
            channels.append(dict(id=name, protocol=c['protocol'], width=width))
            lines += [f'wire [{width-1}:0] data_{idx}={data}; integer completed_{idx}=0;']
            if c['protocol']=='decoupled-v1':
                valid,ready,clock=(signal(k) for k in ('valid','ready','clock'))
                idle_terms.append(f'(!{valid} && {ready})')
                lines += [f'reg held_{idx}=0; reg [{width-1}:0] previous_{idx};',
                          f'always @(posedge {clock}) if (!reset) begin',
                          f'if (held_{idx} && (!{valid} || data_{idx} !== previous_{idx})) $fatal(1,"CLOCKED_HOLD");',
                          f'held_{idx}={valid} && !{ready}; previous_{idx}=data_{idx};',
                          f'if ({valid} && {ready}) begin completed_{idx}++; $fdisplay(log,"F|%0d|%0d|{name}|%0h",$time,epoch,data_{idx}); end end',
                          f'always @(posedge reset) held_{idx}=0;']
            else:
                req=signal('request') if 'request' in c else "1'b0"
                zero=signal('zero') if 'zero' in c else "1'b0"
                ack=signal('acknowledge')
                idle_terms.append(f'({req} == {ack})' if c['protocol']=='two-phase-bundled-v1' else
                                  f'(!({zero} | data_{idx}) && !{ack})' if c['protocol']=='dual-rail-rtz-v1' else
                                  f'(!{req} && !{ack})')
                lines += [f'always @(reset or {req} or {ack} or {zero} or data_{idx}) if (log)',
                          f'$fstrobe(log,"A|%0d|%0d|%0b|{name}|%0b|%0b|%0h|%0h",$time,epoch,reset,{req},{ack},data_{idx},{zero});',
                          f'always @({"" if c["protocol"]=="two-phase-bundled-v1" else "posedge "}{ack}) if (!reset) completed_{idx}++;']
    lines += ['wire all_idle = '+' && '.join(idle_terms)+';', 'task snapshot; begin']
    for idx,c in enumerate(channels):
        lines += [f'$fdisplay(log,"C|%0d|{c["id"]}|%0d",epoch,completed_{idx}); completed_{idx}=0;']
    lines += ['end endtask',
              'always @(posedge in_ack) if (!reset) accepted++;',
              'task automatic send(input [3:0] word, input integer i); begin',
              'in_bits=word; #1000000; in_req=1; wait(in_ack); #1; in_req=0; wait(!in_ack); #1;',
              'if (serial) begin wait(delivered>i); wait(all_idle); #1; end',
              'end endtask',
              f'task receive; integer k; begin for(k=0;k<{count};k++) begin',
              f'wait(out_req); #(serial ? 1 : 1+10000000*((k+{seed})%23)); out_ack=1; delivered++;',
              'wait(!out_req); #(serial ? 1 : 7000000); out_ack=0; #1; end end endtask',
              'task stream; begin fork begin']
    lines += [f'send(4\'h{word:x},{i}); #(serial ? 1 : {1+next(rng)%17000000});' for i,word in enumerate(words)]
    lines += ['end receive(); join #1000000000; end endtask',
              'initial begin log=$fopen("trace.txt","w"); reset=1; #1000000000; epoch=1; reset=0; serial=1; #100000000; stream(); snapshot();',
              'reset=1; #1000000000; epoch=2; reset=0; serial=0; delivered=0; accepted=0; #100000000;',
              'fork : blocked begin']
    lines += [f'send(4\'h{(i*5)%16:x},{i});' for i in range(cap+2)]
    lines += ['end begin #20000000000; end join_any',
              f'if (accepted != {cap}) $fatal(1,"REFERENCE_CAPACITY");',
              'snapshot(); reset=1; disable blocked; #1; in_req=0; out_ack=0; #1000000000;',
              'epoch=3; reset=0; delivered=0; accepted=0; #100000000; stream(); snapshot();',
              '$fclose(log); log=0; $display("REFERENCE_PASS"); $finish; end',
              'initial begin #1000000000000; $fatal(1,"REFERENCE_DEADLINE"); end', 'endmodule']
    return '\n'.join(lines)+'\n', channels, words, clocks


def replay(path, channels, top, words, behavioral=False):
    monitors={c['id']:Protocol(c['protocol'],c['width']) for c in channels if c['protocol']!='decoupled-v1'}
    counts=Counter(); witnesses={}; queue=deque(); latencies=[]; timestamps=[]; inputs=[]; aborted=0; deliveries=Counter()
    rootin=top+'::in'; rootout=top+'::out'; pending=None; old_reset=True; last=-1
    for line in path.read_text(encoding='utf-8').splitlines():
        row=line.split('|'); kind=row[0]
        if kind=='C':
            key=(int(row[1]),row[2]); assert key not in witnesses,'DUPLICATE_WITNESS'; witnesses[key]=int(row[3]); continue
        timestamp,epoch=int(row[1]),int(row[2]); assert timestamp>=last,'TRACE_ORDER'; last=timestamp
        if kind=='F': counts[(epoch,row[3])]+=1; continue
        assert kind=='A','TRACE_SCHEMA'
        reset=row[3]=='1'; name=row[4]
        if reset:
            if not old_reset: aborted+=len(queue);queue.clear();pending=None
            old_reset=True
            for m in monitors.values(): m.reset()
            continue
        old_reset=False
        req,ack,data,zero=(int(value,16) for value in row[5:])
        monitor=monitors[name]; events=[]
        # The documented zero-delay behavioral storage can settle two causal
        # four-phase edges in one sample. Expand only its legal monotonic pairs.
        if behavioral and (monitor.req,monitor.ack,req,ack) in ((0,0,1,1),(1,0,0,1),(1,1,0,0),(0,1,1,0)):
            intermediate={(0,0):(1,0),(1,0):(1,1),(1,1):(0,1),(0,1):(0,0)}[(monitor.req,monitor.ack)]
            events += monitor.observe(*intermediate,data,zero)
        try: events += monitor.observe(req,ack,data,zero)
        except AssertionError as error:
            error.add_note(line); raise
        for event,value in events:
            if event=='complete': counts[(epoch,name)]+=1
            if name==rootin and event=='offer':
                # Integer arithmetic oracle; no HDL equations, controller state or delay assumptions.
                left,right=divmod(value,4);queue.append((left+right,timestamp))
                if epoch in (1,3): inputs.append((epoch,value))
            if name==rootout and event=='offer':
                assert queue and pending is None,'UNEXPECTED_RESULT'
                assert value==queue[0][0],'REFERENCE_SUM_MISMATCH'
                pending=value
                if epoch==1: latencies.append(timestamp-queue[0][1])
            if name==rootout and event=='complete':
                assert pending is not None,'UNEXPECTED_COMPLETION'
                queue.popleft();pending=None;deliveries[epoch]+=1
                if epoch==3: timestamps.append(timestamp)
    assert inputs==[(e,v) for e in (1,3) for v in words],'REFERENCE_INPUT_ACTIVITY'
    assert deliveries=={1:len(words),3:len(words)} and aborted>0 and not queue and pending is None,'REFERENCE_CONSERVATION'
    assert all(m.idle() for m in monitors.values()),'NOT_IDLE'
    expected={(e,c['id']):counts[(e,c['id'])] for e in (1,2,3) for c in channels}
    assert witnesses==expected,'REFERENCE_WITNESS'
    assert all(counts[(e,c['id'])]>0 for e in (1,3) for c in channels),'MISSING_BOUNDARY_ACTIVITY'
    return dict(deliveries=dict(deliveries),aborted=aborted,completion_counts={f'{e}:{n}':v for (e,n),v in counts.items()},
                isolated_offer_latency_fs=dict(min=min(latencies),max=max(latencies),mean=statistics.mean(latencies)),
                stressed_delivery_interval_mean_fs=(timestamps[-1]-timestamps[0])/(len(timestamps)-1))


def execute(style, manifest, ports, sources, seed, directory, mutant=False):
    directory.mkdir(parents=True,exist_ok=True)
    text,channels,words,clocks=bench(style,manifest,ports,seed)
    if mutant:
        # Corrupt actual RTL output before either the observer or sink sees it.
        altered=[]
        for source in sources:
            body=source.read_text(encoding='utf-8')
            if source.name==manifest['top']+'.sv':
                body,n=re.subn(r'assign out_bits = ([^;]+);',r"assign out_bits = (\1) ^ 3'b001;",body)
                assert n==1,'FAULT_TARGET_COUNT'
            copy=directory/source.name;copy.write_text(body,encoding='utf-8');altered.append(copy)
        sources=altered
    path=directory/'bench.sv';path.write_text(text,encoding='utf-8')
    command=['iverilog','-g2012','-s','ReferenceBench','-o',str(directory/'sim'),str(path),*map(str,sources)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (directory/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0,result.stderr
    result=subprocess.run(['vvp',str(directory/'sim')],cwd=directory,capture_output=True,text=True,timeout=60)
    (directory/'simulation.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0 and result.stdout.splitlines().count('REFERENCE_PASS')==1,result.stdout+result.stderr
    try: evidence=replay(directory/'trace.txt',channels,manifest['top'],words,style=='behavioral')
    except AssertionError as error:
        if not mutant or str(error)!='REFERENCE_SUM_MISMATCH': raise
        evidence=dict(diagnostic=str(error))
    else: assert not mutant,'MUTANT_ESCAPED'
    record=dict(style=style,seed=seed,status='EXPECTED_REJECTION' if mutant else 'PASS',evidence=evidence,
                capacity=manifest['design']['capacity'],clock_half_periods_and_offset_fs=clocks,
                compile=command,bench_sha256=sha(path),trace_sha256=sha(directory/'trace.txt'),log_sha256=sha(directory/'simulation.log'))
    (directory/'case.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8');return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'target/generated')
    parser.add_argument('--output',type=Path,default=ROOT/'target/verification/reference')
    parser.add_argument('--seeds',nargs='+',type=int,default=list(range(33)))
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',platform=platform.platform(),seeds=args.seeds,cases=[],faults=[],exports={},sources={},
                checker_sha256={p.name:sha(p) for p in (Path(__file__),ROOT/'verification/phase_reference.py',ROOT/'verification/run_phase.py',ROOT/'tools/check_export.py')})
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        assert args.seeds and len(set(args.seeds))==len(args.seeds) and all(0<=s<2**32 for s in args.seeds),'INVALID_SEEDS'
        report.update(identity());save()
        for style in STYLES:
            generated=args.generated.resolve()/('reference_'+style)
            report['exports'][style]=validate_export(generated)
            m=json.loads((generated/'contract.json').read_text(encoding='utf-8'))['manifest']
            ports=json.loads((generated/'ports.json').read_text(encoding='utf-8'))['nodes'][0]['ports']
            dest=out/'sources'/style;dest.mkdir(parents=True,exist_ok=True);sources=[]
            for original in read_sources(generated):
                p=dest/original.name;p.write_bytes(original.read_bytes());sources.append(p)
            report['sources'][style]={p.name:sha(p) for p in sources}
            for seed in args.seeds: report['cases'].append(execute(style,m,ports,sources,seed,out/f'{style}_{seed}'))
            # Paired with the freshly run first case; mutate no driver or oracle.
            report['faults'].append(execute(style,m,ports,sources,args.seeds[0],out/'faults'/style,True))
            save();print(f'{style}: {len(args.seeds)} cases and wrong-result control PASS',flush=True)
        report['status']='PASS'
    except BaseException as error:
        report.update(status='ERROR',error=str(error));save();raise
    save()


if __name__=='__main__': main()
