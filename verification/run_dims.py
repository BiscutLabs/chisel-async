# SPDX-License-Identifier: Apache-2.0
"""Exhaustive DIMS truth table and every independent arrival/return permutation."""
import argparse
import itertools
import json
from pathlib import Path
import re
import subprocess
from run import ROOT, read_sources
from run_phase import delay_overrides
from compare_controllers import sha
from check_export import validate_export
from campaign_environment import identity


def bench(manifest,seed):
    lines=['module DimsBench; timeunit 1ns; timeprecision 1fs;',
           'reg reset=0; reg [3:0] in_one=0,in_zero=0; reg out_ack=0;',
           'wire [2:0] out_one,out_zero; wire in_ack; integer count=0,v,a,b,k,bit_index;',
           'integer order[0:95];', manifest['top']+' dut(.*);',*delay_overrides(manifest,seed),
           'task reset_dut; begin reset=1; #1; in_one=0; in_zero=0; out_ack=0; #1000; reset=0; #1000; end endtask',
           'task transfer(input integer value,input integer arrival,input integer spacer); integer j,bitno; begin',
           'for(j=0;j<4;j++) begin bitno=order[arrival*4+j];',
           'if(value & (1<<bitno)) in_one[bitno]=1; else in_zero[bitno]=1;',
           '#200; if(j<3 && ((out_one|out_zero)!=0 || in_ack)) $fatal(1,"DIMS_EARLY_VALID"); end',
           'wait (&(out_one|out_zero)); wait(in_ack);',
           'if (out_one !== ((value%4)+(value/4)) || (out_one & out_zero)!=0) $fatal(1,"DIMS_SUM");',
           '#200; out_ack=1;',
           'for(j=0;j<4;j++) begin bitno=order[spacer*4+j]; in_one[bitno]=0;in_zero[bitno]=0;',
           '#200; if(j<3 && ((out_one|out_zero)!=7 || !in_ack)) $fatal(1,"DIMS_EARLY_SPACER"); end',
           'wait ((out_one|out_zero)==0);wait(!in_ack);#1;out_ack=0;#200;count++;end endtask',
           'initial begin']
    for index,order in enumerate(itertools.permutations(range(4))):
        lines+= [f'order[{4*index+j}]={bitno};' for j,bitno in enumerate(order)]
    lines+=['reset_dut(); for(v=0;v<16;v++) for(a=0;a<24;a++) for(b=0;b<24;b++) transfer(v,a,b);',
            '// Reset in each partial-valid and partial-spacer prefix, then restart.',
            'for(k=1;k<4;k++) begin reset_dut(); in_one=(1<<k)-1; #200; reset_dut(); transfer(15,0,23);',
            'in_zero=15;wait(in_ack);out_ack=1;in_zero=15 ^ ((1<<k)-1);#200;reset_dut();transfer(0,23,0);end',
            'if(count!=9222) $fatal(1,"DIMS_ACTIVITY"); $display("DIMS_PASS:9222");$finish;end',
            'initial begin #1000000000;$fatal(1,"DIMS_DEADLINE");end','endmodule']
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generated',type=Path,default=ROOT/'target/generated')
    parser.add_argument('--output',type=Path,default=ROOT/'target/verification/dims')
    args=parser.parse_args();generated=args.generated.resolve()/'reference_core';out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    record=dict(status='RUNNING',cases=[],faults=[],checker_sha256=sha(Path(__file__)))
    def save(): (out/'report.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        record.update(identity());record['export']=validate_export(generated);save()
        m=json.loads((generated/'contract.json').read_text(encoding='utf-8'))['manifest']
        originals={p.name:p.read_text(encoding='utf-8') for p in read_sources(generated)}
        for seed,fault in [*( (s,None) for s in (0,2,3,17,91)),(0,'early_valid'),(0,'stateless_return')]:
            directory=out/(fault or str(seed));directory.mkdir(parents=True,exist_ok=True);selected=dict(originals)
            diagnostic=None
            if fault:
                cell=next(p for p in m['design']['primitives'] if p['id']=='minterm0')['rtl_path'].split('.')[-1]
                top=m['top']+'.sv';text=selected[top]
                if fault=='early_valid':
                    text,n=re.subn('('+re.escape(cell)+r'\s*\([\s\S]*?\.common\s*\()in_zero(\))',r"\g<1>(in_zero | 4'b1000)\2",text);assert n==1
                    diagnostic='DIMS_EARLY_VALID'
                else:
                    pattern='('+re.escape(cell)+r'\s*\([\s\S]*?\.q\s*\()(\w+)(\))'
                    match=re.search(pattern,text);assert match
                    text=re.sub(pattern,lambda x:x[1]+'unused_q'+x[3],text,count=1)
                    text=text.replace(');',');\nwire unused_q;',1).replace('endmodule',f'assign {match[2]} = !reset && (&in_zero);\nendmodule')
                    diagnostic='DIMS_EARLY_SPACER'
                selected[top]=text
            path=directory/'bench.sv';path.write_text(bench(m,seed),encoding='utf-8');sources=[]
            for name,body in selected.items():
                p=directory/name;p.write_text(body,encoding='utf-8');sources.append(p)
            command=['iverilog','-g2012','-s','DimsBench','-o',str(directory/'sim'),str(path),*map(str,sources)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=30)
            (directory/'compile.log').write_text(result.stdout+result.stderr,encoding='utf-8');assert result.returncode==0,result.stderr
            result=subprocess.run(['vvp',str(directory/'sim')],capture_output=True,text=True,timeout=60)
            log=result.stdout+result.stderr;(directory/'simulation.log').write_text(log,encoding='utf-8')
            if fault: assert result.returncode==1 and re.findall(r'FATAL: [^\n]*?: (\w+)',log)==[diagnostic],log
            else: assert result.returncode==0 and log.splitlines().count('DIMS_PASS:9222')==1,log
            row=dict(seed=seed,fault=fault,diagnostic=diagnostic,status='EXPECTED_REJECTION' if fault else 'PASS',
                     deliveries=0 if fault else 9222,compile=command,bench_sha256=sha(path),sources={p.name:sha(p) for p in sources},log_sha256=sha(directory/'simulation.log'))
            record['faults' if fault else 'cases'].append(row);save()
        record['status']='PASS'
    except BaseException as error:
        record.update(status='ERROR',error=str(error));save();raise
    save();print('DIMS PASS: 5 x 9,216 permutations + 30 reset-restart deliveries, two paired controls')


if __name__=='__main__': main()
