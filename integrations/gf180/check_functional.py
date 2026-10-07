# SPDX-License-Identifier: Apache-2.0
"""Check trial adapter polarity/reset against caller-supplied GF180 functional views.

This does not test PVT delays, hazards, aperture or analog behavior.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def run(reference, models, output, iverilog='iverilog', vvp='vvp'):
    record=json.loads((reference/'reference.json').read_text())
    source=reference/'adapters.v'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=record['adapters_sha256']:
        raise ValueError('REFERENCE_ADAPTER_CHANGED')
    if not record['adapters'] or not models:
        raise ValueError('EMPTY_ADAPTER_OR_MODEL_INVENTORY')
    output.mkdir(parents=True,exist_ok=False)
    result=dict(status='RUNNING',scope='GF180 functional views; no timing or physical qualification',
                inputs_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,*models]},adapters=[])
    def save():
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        for entry in record['adapters']:
            name=entry['module']; params=entry['cell']['parameters']; width=int(params['WIDTH'])
            latch=entry['cell']['model']=='ChiselAsyncClosingLatch_v1'
            if latch:
                declarations=f'reg reset=1,closed=1; reg [{width-1}:0] d=0,expected; wire [{width-1}:0] q; integer i;'
                connections='.reset(reset),.closed(closed),.d(d),.q(q)'
                body='''#10; if(q!==0) $fatal(1,"RESET"); reset=0; d='1;
#10; if(q!==0) $fatal(1,"CLOSED_HOLD"); closed=0;
#10; if(q!=={WIDTH{1'b1}}) $fatal(1,"TRANSPARENCY"); closed=1;
#10; d=0; #10; if(q!=={WIDTH{1'b1}}) $fatal(1,"RETENTION"); reset=1;
#10; if(q!==0) $fatal(1,"CLOSED_RESET"); reset=0; closed=0;
#10; if(q!==0) $fatal(1,"REOPEN");
for(i=0;i<WIDTH;i=i+1) begin
  d=0; d[i]=1; expected=d; #10;
  if(q!==expected) $fatal(1,"WALKING_BIT"); closed=1; #10; d=0; #10;
  if(q!==expected) $fatal(1,"WALKING_BIT_RETENTION"); closed=0; #10;
end'''
            else:
                op=int(params['OP'])
                declarations=f'reg reset=1; reg [{width-1}:0] a=0,b=0; wire [{width-1}:0] q; integer i;'
                connections='.reset(reset),.a(a),.b(b),.q(q)'
                expression=['a','~a','a|b'][op]
                body=f'''#10; if(q!==0) $fatal(1,"RESET"); reset=0;
for(i=0;i<4;i=i+1) begin
  a={{WIDTH{{i[0]}}}}; b={{WIDTH{{i[1]}}}};
  #10; if(q!==({expression})) $fatal(1,"GATE_TRUTH_TABLE");
end
for(i=0;i<WIDTH;i=i+1) begin
  a=0; a[i]=1; b=0; #10;
  if(q!==({expression})) $fatal(1,"WALKING_A");
  b=a; a=0; #10; if(q!==({expression})) $fatal(1,"WALKING_B");
end
reset=1; #10; if(q!==0) $fatal(1,"RESET_AFTER_ACTIVITY");'''
            bench=output/f'{name}.sv'
            bench.write_text(f'''`timescale 1ns/1ps
module Test;
localparam WIDTH={width};
{declarations}
{name} dut({connections});
initial begin {body}
$display("CA_GF180_FUNCTIONAL_PASS"); $finish; end
initial begin #10000; $fatal(1,"TIMEOUT"); end
endmodule
''',encoding='utf-8')
            image=output/f'{name}.vvp'
            for phase,command in [('compile',[iverilog,'-g2012','-DFUNCTIONAL','-s','Test','-o',str(image),str(source),*[str(p) for p in models],str(bench)]),
                                  ('run',[vvp,str(image)])]:
                proc=subprocess.run(command,capture_output=True,text=True,timeout=60)
                text=proc.stdout+proc.stderr
                (output/f'{name}-{phase}.log').write_text(text,encoding='utf-8')
                if proc.returncode or (phase=='run' and text.count('CA_GF180_FUNCTIONAL_PASS')!=1):
                    raise RuntimeError(f'GF180_FUNCTIONAL_FAILED {name} {phase}: {text}')
            result['adapters'].append(name); save()
        result['status']='FUNCTIONAL_VIEWS_PASS'
    except BaseException as error:
        result.update(status='ERROR',error=str(error)); raise
    finally:
        save()
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--model',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--iverilog',default='iverilog'); parser.add_argument('--vvp',default='vvp')
    args=parser.parse_args()
    result=run(args.reference,args.model,args.output,args.iverilog,args.vvp)
    print(f"{result['status']}: {len(result['adapters'])} adapters")
