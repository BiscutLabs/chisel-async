# SPDX-License-Identifier: Apache-2.0
"""History closure skew/aperture budget on emitted production ToTwoPhase RTL."""
import argparse
import itertools
import json
from pathlib import Path
import re
import subprocess
from run import ROOT, read_sources
from compare_controllers import sha
from run_phase import nodes
from check_export import validate_export
from campaign_environment import identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'target/generated')
    parser.add_argument('--output',type=Path,default=ROOT/'target/verification/closure')
    args=parser.parse_args();generated=args.generated.resolve()/'phase_to_two';out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',cases=[],faults=[],checker_sha256=sha(Path(__file__)),
                bench_sha256=sha(ROOT/'verification/phase_closure.sv'))
    def save(): (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    report.update(identity());report['export']=validate_export(generated);save()
    manifest=json.loads((generated/'contract.json').read_text(encoding='utf-8'))['manifest']
    node=next(n for n in nodes(manifest['design']) if any(p['id']=='history' for p in n['primitives']))
    model=node['module'];cells={p['id']:p['rtl_path'].split('.')[-1] for p in node['primitives']}
    original={p.name:p.read_text(encoding='utf-8') for p in read_sources(generated)}
    def pin(name):
        text=original[model+'.sv'];instance=cells[name]
        return re.search(re.escape(instance)+r'\s*\([\s\S]*?\.q\s*\((\w+)\)',text)[1]
    paths={'C':'history_close','T':'request_phase','H':'history','X':'acknowledge','G':'request_guard'}
    insert=f'{model} dut(.reset(reset),.in_req(req4),.in_bits(8\'h5a),.in_ack(ack4),.out_req(req2),.out_bits(),.out_ack(ack2));\n'
    insert+='\n'.join(f'defparam dut.{cells[name]}.DELAY_FS={key};' for key,name in paths.items())
    insert+=f'\nassign closed=dut.{pin("history_close")}; assign history=dut.{pin("history")};'
    template=(ROOT/'verification/phase_closure.sv').read_text(encoding='utf-8').replace('// DUT_INSERT',insert)
    cases=[dict(C=c,T=t,H=h,X=x,G=c+1 if tight else c*4) for c,(t,h,x),tight in itertools.product(
        (1000000,10000000,100000000),itertools.product((1,10000000),repeat=3),(False,True))]
    # Reviewer's four latch/toggle pairs, with explicit skew 0..12 ns independently.
    cases += [dict(C=c*1000000,T=t*1000000,H=h*1000000,X=1000000,G=40000000)
              for h,t,c in itertools.product((1,5),(1,5),range(13))]
    def run_case(index,params,fault):
        directory=out/(fault or f'case_{index}');directory.mkdir(parents=True,exist_ok=True)
        selected=dict(original);values=dict(params)
        diagnostic=None
        if fault=='unguarded': values['G']=0;diagnostic='HISTORY_NOT_ISOLATED_BEFORE_ACK'
        if fault=='pre_toggle':
            text=selected[model+'.sv']
            text,n=re.subn(r'\.trigger\s*\(in_req\)',f'.trigger ({pin("request_guard")})',text);assert n==1
            text,n=re.subn(r'(\.a\s*\()'+re.escape(pin('request_phase'))+r'(\))',r'\g<1>in_req\2',text);assert n==1
            text,n=re.subn(r'assign out_req = \w+;',f'assign out_req = {pin("request_phase")};',text);assert n==1
            selected[model+'.sv']=text;diagnostic='REQUEST_PHASE_LOST'
        path=directory/'bench.sv';path.write_text(template,encoding='utf-8')
        sources=[]
        for name,body in selected.items():
            p=directory/name;p.write_text(body,encoding='utf-8');sources.append(p)
        command=['iverilog','-g2012','-s','ReviewAdapterBench','-o',str(directory/'sim'),
                 *[f'-PReviewAdapterBench.{k}={v}' for k,v in values.items()],str(path),*map(str,sources)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        (directory/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8');assert result.returncode==0,result.stderr
        result=subprocess.run(['vvp',str(directory/'sim')],capture_output=True,text=True,timeout=30)
        log=result.stdout+result.stderr;(directory/'simulation.log').write_text(log,encoding='utf-8')
        if diagnostic:
            assert result.returncode==1 and re.findall(r'FATAL: [^\n]*?: (\w+)',log)==[diagnostic],log
        else: assert result.returncode==0 and log.count('ADAPTER_REVIEW_PASS transfers=22 reset_windows=6')==1,log
        row=dict(parameters=values,diagnostic=diagnostic,status='EXPECTED_REJECTION' if fault else 'PASS',
                 compile=command,bench_sha256=sha(path),sources={p.name:sha(p) for p in sources},log_sha256=sha(directory/'simulation.log'))
        (report['faults'] if fault else report['cases']).append(row);save()
    try:
        for index,params in enumerate(cases): run_case(index,params,None)
        baseline=dict(C=10000000,T=1000000,H=1000000,X=1000000,G=40000000)
        run_case('paired',baseline,None)
        for fault in ('unguarded','pre_toggle'): run_case(None,baseline,fault)
        report['status']='PASS'
    except BaseException as error:
        report.update(status='ERROR',error=str(error));save();raise
    save();print(f'Closure PASS: {len(report["cases"])} cases, two paired controls')


if __name__=='__main__': main()
