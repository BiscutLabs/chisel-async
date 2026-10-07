# SPDX-License-Identifier: Apache-2.0
"""Sample trial adapters against supplied GF180 Liberty corners with OpenSTA.

Records cell-only D-to-Q/control propagation. Does not check latch aperture,
setup/hold, reset recovery, feedback hazards, layout or extracted wires.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def run(reference, libraries, output, sta, slew_ns, load_pf):
    if not libraries or slew_ns <= 0 or load_pf <= 0:
        raise ValueError('MISSING_CORNERS_OR_LOAD_CONDITIONS')
    description = json.loads((reference/'reference.json').read_text())
    netlist=reference/'adapters.v'
    if hashlib.sha256(netlist.read_bytes()).hexdigest()!=description['adapters_sha256']:
        raise ValueError('REFERENCE_ADAPTER_CHANGED')
    if not description['adapters']:
        raise ValueError('NO_REFERENCE_ADAPTERS')
    output.mkdir(parents=True, exist_ok=False)
    files = [reference/'reference.json',netlist,*libraries,
             ROOT/'src/main/resources/chiselasync/timing-endpoints.tcl',
             ROOT/'src/main/resources/chiselasync/timing-checks.tcl']
    report=dict(status='RUNNING',scope='Liberty propagation samples only; no physical qualification',
                input_slew_ns=slew_ns,output_load_pf=load_pf,
                inputs_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},samples=[])
    def save():
        (output/'samples.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        for index, lib in enumerate(libraries):
            for entry in description['adapters']:
                name=entry['module']; params=entry['cell']['parameters']
                latch=entry['cell']['model']=='ChiselAsyncClosingLatch_v1'
                source='d' if latch else 'a'
                setup='set_case_analysis 0 [get_ports closed]\n' if latch else (
                    'set_case_analysis 0 [get_ports b*]\n' if int(params['OP'])==2 else '')
                measurement = ('ca_arc sample [get_pins bit_*/D] [get_pins bit_*/Q] 0 none' if latch else
                    f'ca_measure sample [list -from [get_ports {source}*] -to [get_ports q*]] 0 none')
                command=f'''read_liberty {{{lib.resolve().as_posix()}}}
read_verilog {{{netlist.resolve().as_posix()}}}
link_design -no_black_boxes {name}
source {{{files[-2].as_posix()}}}
source {{{files[-1].as_posix()}}}
set_cmd_units -time ns -capacitance pF
set_case_analysis 0 [get_ports reset]
{setup}set_input_transition {slew_ns} [all_inputs]
set_load {load_pf} [all_outputs]
{measurement}
puts CA_GF180_SAMPLE_PASS
'''
                script=output/f'{index}-{name}.tcl'
                script.write_text('if {[catch {\n'+command+'\n} message]} {puts stderr "CA_SAMPLE_FAILURE: $message"; exit 1}\nexit 0\n',encoding='utf-8')
                proc=subprocess.run([sta,'-exit',str(script.resolve())],capture_output=True,text=True,timeout=60)
                text=proc.stdout+proc.stderr
                (output/f'{index}-{name}.log').write_text(text,encoding='utf-8')
                match=re.search(r'^CA_TIMING_PATH id=sample min_ns=(\S+) max_ns=(\S+)$',text,re.M)
                if proc.returncode or not match or text.count('CA_GF180_SAMPLE_PASS')!=1:
                    raise RuntimeError(f'GF180_SAMPLE_FAILED {name}: {text}')
                lo,hi=map(float,match.groups())
                report['samples'].append(dict(corner=lib.name,module=name,min_ns=lo,max_ns=hi))
                save()
        report['status']='PROPAGATION_SAMPLES_COMPLETE'
    except BaseException as error:
        report.update(status='ERROR',error=str(error))
        raise
    finally:
        save()
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--liberty',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sta',default='sta')
    parser.add_argument('--slew-ns',type=float,required=True)
    parser.add_argument('--load-pf',type=float,required=True)
    args=parser.parse_args()
    report=run(args.reference,args.liberty,args.output,args.sta,args.slew_ns,args.load_pf)
    print(f"{report['status']}: {len(report['samples'])} samples")
