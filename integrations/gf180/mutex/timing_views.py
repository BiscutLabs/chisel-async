# SPDX-License-Identifier: Apache-2.0
"""Scenario-only Mutex timing tables, never a general arbiter Liberty model.

The idle request cycle starts after POR with both requests/grants low. The reset
scenario starts with a retained, uncontended winner. Neither describes contention,
unresolved reset, request reuse before grant-low, power, or minimum pulse widths.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from characterize import CORNERS, header, pwl, sha
from layout import TOP, OUTLINE
from layout_checks import rc_connectivity
from waveform import data, validate_transient, check_held

SLEWS=(.05,.5,5.)  # full linear input ramp, ns; Liberty uses 20--80% (0.6x)
LOADS=(.005,.02,.05)  # pF on the winning output; the other is fixed at 0.05 pF
WAVE_COLUMNS=['time','v(r0)','v(r1)','v(reset)','v(g0)','v(g1)']


def cases():
    for corner in CORNERS:
        for slew in SLEWS:
            for load in LOADS:
                for side in (0,1):
                    for kind in ('idle','reset'):
                        yield dict(corner=corner,slew=slew,load=load,side=side,kind=kind)


def deck(case,models,circuit,step_scale=1,wave=None):
    v=case['corner'][3];s=case['slew'];side=case['side']
    active='r'+str(side);grant='g'+str(side);other='r'+str(1-side)
    request=[(0,0),(20,0),(20+s,v)]
    reset=[(0,v),(10,v),(10+s,0)]
    source='req';trigger=active;edge='rise';start=20
    if case['kind']=='idle':request += [(55,v),(55+s,0)]
    else:
        reset += [(55,0),(55+s,v)];source='rst';trigger='reset';start=55
    step=min(s/20,.01)*step_scale
    text=header(models,circuit,case['corner'])+f'''Vreq {active} 0 {pwl(request)}
Vother {other} 0 0
Vrst reset 0 {pwl(reset)}
XD reset r0 r1 g0 g1 vdd 0 {TOP}
CG0 g0 0 {case['load'] if side==0 else .05}p
CG1 g1 0 {case['load'] if side==1 else .05}p
.control
set wr_singlescale
set wr_vecnames
tran {step}n 80n
meas tran initial_g0 FIND v(g0) AT=19n
meas tran initial_g1 FIND v(g1) AT=19n
meas tran winner FIND v({grant}) AT=50n
meas tran loser_max MAX v(g{1-side}) FROM=19n TO=80n
meas tran final_g0 FIND v(g0) AT=79n
meas tran final_g1 FIND v(g1) AT=79n
meas tran q_input INTEG i(V{source}) FROM={start-1}n TO={start+15}n
meas tran idle_current FIND i(V{source}) AT={start-1}n
'''
    if case['kind']=='idle':
        text+=f'''meas tran rise_delay TRIG v({active}) VAL={.5*v} TD=19n RISE=1 TARG v({grant}) VAL={.5*v} TD=19n RISE=1
meas tran rise_slew TRIG v({grant}) VAL={.2*v} TD=19n RISE=1 TARG v({grant}) VAL={.8*v} TD=19n RISE=1
meas tran fall_delay TRIG v({active}) VAL={.5*v} TD=54n FALL=1 TARG v({grant}) VAL={.5*v} TD=54n FALL=1
meas tran fall_slew TRIG v({grant}) VAL={.8*v} TD=54n FALL=1 TARG v({grant}) VAL={.2*v} TD=54n FALL=1
meas tran q_fall INTEG i(Vreq) FROM=54n TO=70n
meas tran fall_current FIND i(Vreq) AT=54n
'''
    else:
        text+=f'''meas tran fall_delay TRIG v(reset) VAL={.5*v} TD=54n RISE=1 TARG v({grant}) VAL={.5*v} TD=54n FALL=1
meas tran fall_slew TRIG v({grant}) VAL={.8*v} TD=54n FALL=1 TARG v({grant}) VAL={.2*v} TD=54n FALL=1
'''
    if wave is not None:text+=f'wrdata {wave.as_posix()} '+ ' '.join(WAVE_COLUMNS[1:])+'\n'
    return text+'quit\n.endc\n.end\n'


def check_wave(rows,case):
    v=case['corner'][3]
    errors=check_held(rows,v)
    if any(not -.1*v<=r[c]<=1.1*v for r in rows for c in (4,5)):
        errors.append('MUTEX_TIMING_OUTPUT_RAIL')
    # Each characterized edge must be a single crossing, not the first edge of
    # a glitch that eventually settles. Check all standard measurement levels.
    grant=4+case['side'];active=[r for r in rows if r[0]>=19e-9]
    for fraction in (.2,.3,.5,.7,.8):
        level=fraction*v
        directions=[b[grant]>=level for a,b in zip(active,active[1:])
                    if (a[grant]>=level)!=(b[grant]>=level)]
        if directions != [True,False]:errors.append('MUTEX_TIMING_RECROSSING')
    if errors:raise ValueError(','.join(sorted(set(errors))))


def measurements(text,case):
    if re.search(r'(?im)^\s*(?:error|fatal)|failed|out of interval',text):
        raise ValueError('MUTEX_TIMING_SIMULATION_ERROR')
    values={k:float(v) for k,v in re.findall(r'(?m)^([a-z][a-z_0-9]*)\s*=\s*([-+\d.eE]+)',text)}
    needed={'initial_g0','initial_g1','winner','loser_max','final_g0','final_g1',
            'q_input','idle_current','fall_delay','fall_slew'}
    if case['kind']=='idle':needed|={'rise_delay','rise_slew','q_fall','fall_current'}
    if not needed<=values.keys() or any(not math.isfinite(values[n]) for n in needed):
        raise ValueError('MUTEX_TIMING_MISSING_MEASUREMENT')
    v=case['corner'][3]
    if any(abs(values[n])>.3*v for n in ('initial_g0','initial_g1','final_g0','final_g1')):
        raise ValueError('MUTEX_TIMING_NOT_QUIESCENT')
    if values['winner']<.7*v or values['loser_max']>.3*v:
        raise ValueError('MUTEX_TIMING_WRONG_WINNER')
    result={n+'_ns':values[n]*1e9 for n in needed if n.endswith(('_delay','_slew'))}
    # Charge over the entire ramp and settled tail, with the pre-edge leakage
    # removed. This is effective capacitance in this scenario, not a DC wire-C.
    cap=abs(values['q_input']-values['idle_current']*16e-9)/v*1e12
    if case['kind']=='idle':
        cap=max(cap,abs(values['q_fall']-values['fall_current']*16e-9)/v*1e12)
    result['effective_input_cap_pf']=cap
    if cap<=0 or any(result[k]<=0 for k in result if k.endswith('slew_ns')):
        raise ValueError('MUTEX_TIMING_INVALID_MEASUREMENT')
    return result


def liberty(corner,results):
    inventory={(c['side'],c['kind'],c['slew'],c['load']):c['measurements'] for c in results}
    expected={(side,kind,s,l) for side in (0,1) for kind in ('idle','reset') for s in SLEWS for l in LOADS}
    if inventory.keys()!=expected or len(results)!=len(expected):raise ValueError('MUTEX_TIMING_GRID_INCOMPLETE')
    def table(kind,side,metric):
        return ',\n'.join('          "'+', '.join(f'{inventory[side,kind,s,l][metric]:.9g}' for l in LOADS)+'"' for s in SLEWS)
    lines=['/* EXPERIMENTAL CHARACTERIZATION ONLY. Boolean when conditions do NOT',
        ' * prove the required prior idle/retained-winner state. Not a general',
        ' * arbiter STA model; contention has no finite delay bound. Use report.json',
        ' * preconditions and domain; other grant load must be exactly 0.05 pF.',
        ' * No function, reset-release, min-pulse or power model is provided. */',
        f'library ({TOP}_{corner[0]}_scenarios) {{',
        '  delay_model : table_lookup;', '  time_unit : "1ns";',
        '  voltage_unit : "1V";', '  current_unit : "1mA";',
        '  capacitive_load_unit (1,pf);','  pulling_resistance_unit : "1kohm";',
        f'  nom_voltage : {corner[3]};',f'  nom_temperature : {corner[2]};','  nom_process : 1;',
        '  input_threshold_pct_rise : 50;','  input_threshold_pct_fall : 50;',
        '  output_threshold_pct_rise : 50;','  output_threshold_pct_fall : 50;',
        '  slew_lower_threshold_pct_rise : 20;','  slew_upper_threshold_pct_rise : 80;',
        '  slew_lower_threshold_pct_fall : 20;','  slew_upper_threshold_pct_fall : 80;',
        '  lu_table_template (delay_grid) {',
        '    variable_1 : input_net_transition;','    variable_2 : total_output_net_capacitance;',
        '    index_1 ("'+', '.join(f'{s*.6:g}' for s in SLEWS)+'");',
        '    index_2 ("'+', '.join(map(str,LOADS))+'");','  }',
        f'  cell ({TOP}) {{',f'    area : {OUTLINE[0]*OUTLINE[1]:.6f};',
        '    dont_use : true;','    is_macro_cell : true;',
        '    pg_pin (VDD) { voltage_name : VDD; pg_type : primary_power; }',
        '    pg_pin (VSS) { voltage_name : VSS; pg_type : primary_ground; }']
    for pin in ('R0','R1','RESET'):
        caps=[m['effective_input_cap_pf'] for (side,kind,_,_),m in inventory.items()
              if (kind=='reset' if pin=='RESET' else kind=='idle' and side==int(pin[-1]))]
        lines += [f'    pin ({pin}) {{ direction : input; capacitance : {max(caps):.9g}; max_transition : {max(SLEWS)*.6:g}; }}']
    for side in (0,1):
        lines += [f'    pin (G{side}) {{','      direction : output;',
                  f'      max_capacitance : {max(LOADS):g};',
                  '      related_power_pin : VDD;','      related_ground_pin : VSS;']
        for kind in ('idle','reset'):
            related=f'R{side}' if kind=='idle' else 'RESET'
            condition=f'!R{1-side} & !RESET' if kind=='idle' else f'R{side} & !R{1-side}'
            lines += ['      timing () {',f'        related_pin : "{related}";',
                      f'        when : "{condition}";',
                      '        timing_sense : '+('positive_unate;' if kind=='idle' else 'negative_unate;'),
                      '        timing_type : '+('combinational;' if kind=='idle' else 'combinational_fall;')]
            for field,metric in [('cell_rise','rise_delay_ns'),('rise_transition','rise_slew_ns'),
                                 ('cell_fall','fall_delay_ns'),('fall_transition','fall_slew_ns')]:
                if kind=='reset' and 'rise' in field:continue
                lines += [f'        {field} (delay_grid) {{','          values (',table(kind,side,metric)+');','        }']
            lines+=['      }']
        lines+=['    }']
    return '\n'.join(lines+['  }','}',''])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('circuit','lvs-circuit','model-dir','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--ngspice',default='ngspice');p.add_argument('--jobs',type=int,default=4)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    exe=Path(shutil.which(a.ngspice) or a.ngspice).resolve()
    sources=[Path(__file__),Path(__file__).with_name('characterize.py'),Path(__file__).with_name('layout.py'),
        Path(__file__).with_name('layout_checks.py'),Path(__file__).with_name('waveform.py'),a.circuit,a.lvs_circuit,exe,
        a.model_dir/'design.ngspice',a.model_dir/'sm141064.ngspice']
    hashes={str(x.resolve()):sha(x) for x in sources}
    report=dict(status='running',physical_qualification=False,inputs_sha256=hashes,
        rc=rc_connectivity(a.lvs_circuit,a.circuit),cases=[],maximum_contention_delay_ns=None,
        preconditions={'idle':'POR settled; both requests and grants low; opposite request remains low; reset stays low',
                      'reset':'retained uncontended winner; opposite request low; destructive reset assertion only'},
        exclusions=['contention', 'unresolved reset', 'reset release', 'minimum pulses', 'variation/noise',
                    'RC corners', 'internal/leakage power', 'general STA adoption'],
        input_capacitance='maximum measured effective edge charge / V in these scenarios only')
    report['domain']=dict(input_slew_20_80_ns=[min(SLEWS)*.6,max(SLEWS)*.6],
        winning_output_load_pf=[min(LOADS),max(LOADS)],other_output_load_pf=.05,
        interpolation='sample grid only; unsampled interpolation not qualified',extrapolation_allowed=False)
    def run(index,case,scale=1):
        folder=out/str(index);folder.mkdir()
        wave=folder/'wave.tsv'
        probe=folder/'probe.spice';probe.write_text(deck(case,a.model_dir.resolve(),a.circuit.resolve(),scale,wave))
        log=folder/'simulation.log'
        try:
            with log.open('w') as stream:r=subprocess.run([str(exe),'-n','-b',str(probe)],stdout=stream,stderr=subprocess.STDOUT,timeout=600)
            if r.returncode:raise ValueError('MUTEX_TIMING_TOOL_FAILED')
            names,rows=data(wave)
            validate_transient(names,rows,80,min(case['slew']/20,.01)*scale,columns=WAVE_COLUMNS)
            check_wave(rows,case)
            return case|dict(index=index,passed=True,measurements=measurements(log.read_text(),case),step_scale=scale)
        except (ValueError,OSError,subprocess.TimeoutExpired) as error:
            return case|dict(index=index,passed=False,error=str(error),step_scale=scale)
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        futures=[pool.submit(run,i,c) for i,c in enumerate(cases())]
        for f in as_completed(futures):
            result=f.result();report['cases'].append(result);print(result['index'],result['passed'],flush=True)
    report['cases'].sort(key=lambda c:c['index'])
    report['status']='pass' if all(c['passed'] for c in report['cases']) else 'fail'
    if report['status']=='pass':
        # Refine the fastest-edge/highest-load case for each measured scenario.
        selected=[c for c in report['cases'] if c['corner'][0]=='ff_n40C_3v60' and c['slew']==min(SLEWS) and c['load']==max(LOADS)]
        report['refinement']=[]
        for c in selected:
            fine=run('fine-'+str(c['index']),c,.5)
            delta=max((abs(c['measurements'][k]-fine['measurements'][k]) for k in c['measurements'] if k.endswith('_ns')),default=math.inf) if fine['passed'] else math.inf
            report['refinement'].append(fine|{'maximum_timing_delta_ns':delta})
            if not math.isfinite(delta) or delta>.005:report['status']='fail'
    if any(sha(x)!=hashes[str(x.resolve())] for x in sources):report['status']='fail';report['error']='MUTEX_TIMING_INPUT_CHANGED'
    if report['status']=='pass':
        for corner in CORNERS:
            (out/(TOP+'__'+corner[0]+'__scenarios.lib')).write_text(liberty(corner,[c for c in report['cases'] if c['corner']==corner]))
    report['outputs_sha256']={str(x):sha(x) for x in sorted(out.rglob('*')) if x.is_file()}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(report['status']!='pass')


if __name__=='__main__':main()
