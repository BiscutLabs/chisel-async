# SPDX-License-Identifier: Apache-2.0
"""Loaded, distributed-RC Mutex samples using the existing waveform oracles.

This is a bounded experiment, not metastability, mismatch or noise qualification.
Only the whole-cell sequence/contention campaign applies to an extracted circuit;
standalone filter DC experiments remain in characterize.py on the schematic.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import shutil
import subprocess

from characterize import CORNERS, analyze_transient, header, pwl, sha, sampled, edge
from layout_checks import rc_connectivity, spice
from waveform import data, validate_transient, check_held

HERE = Path(__file__).resolve().parent
COLUMNS = ['time', 'v(r0)', 'v(r1)', 'v(reset)', 'v(g0)', 'v(g1)',
           'v(xd.x_n0)', 'v(xd.x_n1)', 'v(xd.x_f0)', 'v(xd.x_f1)']


def inventory():
    for corner in CORNERS:
        for loads in ((.005, .005), (.05, .05), (.05, .005), (.005, .05)):
            for slews in ((.05, .05), (.05, 5), (5, .05)):
                for reverse in (False,True):
                    yield dict(kind='sequence', corner=corner, loads=loads, slews=slews, skew=0, reverse=reverse)
                for skew in (-1, -.001, 0, .001, 1):
                    yield dict(kind='contention', corner=corner, loads=loads, slews=slews, skew=skew)

    for corner in CORNERS:
        for reverse in (False,True):
            for slew in (.05,5):
                for kind in ('reset','reset-contention'):
                    yield dict(kind=kind,corner=corner,loads=(.05,.005),slews=(slew,slew),skew=0,reverse=reverse)


def deck(case, models, circuit, wave, step_scale=1):
    v = case['corner'][3]
    s0, s1 = case['slews']
    if case['kind'] == 'contention':
        skew = case['skew']
        r0 = [(0, 0), (20, 0), (20+s0, v)]
        r1 = [(0, 0), (20+skew, 0), (20+skew+s1, v)]
        reset = [(0, v), (10, v), (10+s0, 0)]
        finish = 60
    elif case['kind'].startswith('reset'):
        r0=[(0,0),(20,0),(20+s0,v),(90,v),(90+s0,0)]
        r1=([(0,0),(20,0),(20+s1,v),(90,v),(90+s1,0)] if case['kind']=='reset-contention'
            else [(0,0),(140,0),(140+s1,v)])
        reset=[(0,v),(10,v),(10+s0,0),(40,0),(40+s0,v),
               (60,v),(60+s0,0),(110,0),(110+s0,v),(125,v),(125+s0,0)]
        finish=170
    else:
        r0 = [(0, 0), (20, 0), (20+s0, v), (70, v), (70+s0, 0)]
        r1 = [(0, 0), (40, 0), (40+s1, v), (100, v), (100+s1, 0),
              (160, 0), (160+s1, v), (190, v), (190+s1, 0)]
        reset = [(0, v), (10, v), (10+s0, 0), (125, 0), (125+s0, v),
                 (145, v), (145+s0, 0)]
        finish = 230
    step = min(s0, s1, .2)/20*step_scale
    if case.get('reverse'):r0,r1=r1,r0
    text = header(models, circuit, case['corner']) + f'''VR0 r0 0 {pwl(r0)}
VR1 r1 0 {pwl(r1)}
VRESET reset 0 {pwl(reset)}
XD reset r0 r1 g0 g1 vdd 0 ca_mutex_gf180_candidate
CG0 g0 0 {case['loads'][0]}p
CG1 g1 0 {case['loads'][1]}p
.control
set wr_singlescale
set wr_vecnames
tran {step}n {finish}n
wrdata {wave.as_posix()} {' '.join(COLUMNS[1:])}
quit
.endc
.end
'''
    return text, finish, step


def analyze(rows, case):
    if case.get('reverse'):
        rows=[[r[i] for i in (0,2,1,3,5,4,7,6,9,8)] for r in rows]
    v=case['corner'][3]
    if not case['kind'].startswith('reset'):
        return analyze_transient(rows,v,case['kind'])
    errors=check_held(rows,v)
    if any(r[4]<-.1*v or r[5]<-.1*v or r[4]>1.1*v or r[5]>1.1*v for r in rows):
        errors.append('MUTEX_ANALOG_OUTPUT_RAIL')
    if any(max(r[4],r[5])>.3*v for r in rows if 55e-9<=r[0]<=60e-9 or 120e-9<=r[0]<=125e-9):
        errors.append('MUTEX_RESET_SETTLED_OUTPUT_NOT_LOW')
    if any(r[4]>.3*v and r[5]>.3*v for r in rows):errors.append('MUTEX_RESET_GRANT_OVERLAP')
    # Do not require finite resolution from a contended arbiter; reset must clear
    # its outputs even if no winner has resolved. A held stale request may regrant.
    expected=((55,0,0),(105,0,0),(120,0,0),(135,0,0))
    if case['kind']=='reset':expected += ((35,1,0),(80,1,0),(165,0,1))
    for when,a,b in expected:
        for col,bit in ((4,a),(5,b)):
            value=sampled(rows,when,col)
            if (value<.7*v) if bit else (value>.3*v):errors.append(f'MUTEX_RESET_STATE_{when}_{col}')
    result=dict(errors=errors, active_reset_is_legal_owner_operation=False)
    if case['kind']=='reset-contention':
        result['unresolved_before_reset']=max(sampled(rows,39.9,4),sampled(rows,39.9,5))<.7*v
    if case['kind']=='reset':
        assertion=edge(rows,3,.5*v,39,True);clear=edge(rows,4,.3*v,39,False)
        if assertion is None or clear is None:errors.append('MUTEX_RESET_MISSING_TRANSITION')
        else:result['reset_to_clear_ns']=clear-assertion
    return result


def replay(report_path, output):
    """Rerun current waveform oracles after a checker fix; no new simulation."""
    old=json.loads(report_path.read_text())
    if old['status'] != 'pass':raise ValueError('MUTEX_REPLAY_INCOMPLETE_RUN')
    expected={tuple_key(c) for c in inventory()}
    base={tuple_key(c) for c in inventory() if not c['kind'].startswith('reset') and not c.get('reverse',False)}
    supplement=expected-base
    if not old.get('unchanged_inputs',False):raise ValueError('MUTEX_REPLAY_CHANGED_RUN_INPUTS')
    for name,digest in old['inputs_sha256'].items():
        if name.endswith(('.spice','.ngspice')) and sha(Path(name))!=digest:
            raise ValueError('MUTEX_REPLAY_CHANGED_CIRCUIT_OR_MODEL')
    circuits=[Path(n) for n in old['inputs_sha256'] if Path(n).suffix=='.spice' and spice(Path(n))[2]]
    models=[Path(n).parent for n in old['inputs_sha256'] if Path(n).name=='design.ngspice']
    if len(circuits)!=1 or len(models)!=1:raise ValueError('MUTEX_REPLAY_INPUT_BINDING')
    seen=set(); results=[]; measured={}
    for case in old['cases']:
        key=tuple_key(case)
        if tuple(case['corner']) not in CORNERS:raise ValueError('MUTEX_REPLAY_CORNER')
        if case.get('returncode')!=0 or not case.get('passed'):raise ValueError('MUTEX_REPLAY_EXECUTION_FAILED')
        if key not in expected:raise ValueError('MUTEX_REPLAY_UNKNOWN_CASE')
        if (key,case.get('half_step',False)) in seen:raise ValueError('MUTEX_REPLAY_DUPLICATE_CASE')
        fine=case.get('half_step',False)
        expected_step=min(*case['slews'],.2)/20*(.5 if fine else 1)
        step=case['maximum_step_ns']
        if not math.isfinite(step) or not math.isclose(step,expected_step,rel_tol=1e-12):
            raise ValueError('MUTEX_REPLAY_WRONG_TIMESTEP')
        seen.add((key,fine))
        files={Path(p).name:Path(p) for p in case['outputs_sha256']}
        if set(files)!={'wave.tsv','probe.spice','simulation.log'}:raise ValueError('MUTEX_REPLAY_MISSING_OUTPUT')
        for name,digest in case['outputs_sha256'].items():
            if sha(Path(name))!=digest:raise ValueError('MUTEX_REPLAY_OUTPUT_CHANGED')
        wave=files['wave.tsv']
        expected_deck,_,_=deck(case,models[0],circuits[0],wave,.5 if fine else 1)
        if files['probe.spice'].read_text()!=expected_deck:raise ValueError('MUTEX_REPLAY_STIMULUS_CHANGED')
        names,rows=data(wave)
        finish=60 if case['kind']=='contention' else 170 if case['kind'].startswith('reset') else 230
        validate_transient(names,rows,finish,case['maximum_step_ns'],columns=COLUMNS)
        measured[key,fine]=analyze(rows,case)
        results.append(dict(index=case['index'],kind=case['kind'],reverse=case.get('reverse',False),
                            **measured[key,fine]))
    if {k for k,half in seen if not half} not in (expected,base,supplement):
        raise ValueError('MUTEX_REPLAY_INCOMPLETE_INVENTORY')
    present={k for k,half in seen if not half}
    pair=tuple_key(dict(kind='sequence',corner=['ff_n40C_3v60'],loads=(.05,.005),slews=(.05,.05),skew=0,reverse=present==supplement))
    if {k for k,half in seen if half}!={pair}:raise ValueError('MUTEX_REPLAY_WRONG_CONVERGENCE_CASE')
    coarse,fine=measured[pair,False],measured[pair,True]
    metrics=['uncontended_to_vih_ns','release0_to_vil_ns','release1_to_vil_ns','quiet_vil_to_vih_ns']
    if any(k not in coarse or k not in fine for k in metrics):raise ValueError('MUTEX_REPLAY_MISSING_CONVERGENCE')
    delta=max(abs(coarse[k]-fine[k]) for k in metrics)
    if not math.isfinite(delta) or delta>.005:raise ValueError('MUTEX_REPLAY_TIMESTEP_NOT_CONVERGED')
    report=dict(status='pass' if results and all(not c['errors'] for c in results) else 'fail',
        physical_qualification=False,spice_runs=0,half_step_max_delta_ns=delta,source_report=str(report_path),
        inputs_sha256={str(p):sha(p) for p in (report_path,Path(__file__),HERE/'characterize.py',HERE/'waveform.py',HERE/'contention.py',HERE/'layout_checks.py')},cases=results)
    output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report['status']=='pass'


def tuple_key(case):
    return (case['kind'],case['corner'][0],tuple(case['loads']),tuple(case['slews']),
            case['skew'],case.get('reverse',False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--circuit', type=Path)
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--lvs-circuit', type=Path)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ngspice', default='ngspice')
    parser.add_argument('--campaign',choices=('all','base','supplement'),default='all',
        help='supplement covers reverse handover and active reset; base is the original forward sweep')
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if args.replay:
        raise SystemExit(0 if replay(args.replay.resolve(),args.output.resolve()) else 1)
    if not all((args.circuit,args.lvs_circuit,args.model_dir)):
        parser.error('--circuit, --lvs-circuit and --model-dir are required for simulation')
    if not 1 <= args.jobs <= 32 or args.timeout <= 0:
        parser.error('jobs must be 1..32 and timeout positive')
    circuit, baseline, models, out = (p.resolve() for p in
        (args.circuit, args.lvs_circuit, args.model_dir, args.output))
    audit = rc_connectivity(baseline, circuit)
    out.mkdir(parents=True, exist_ok=False)
    exe = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
    inputs = [circuit, baseline, exe, Path(__file__), HERE/'layout_checks.py',
              HERE/'characterize.py', HERE/'waveform.py', HERE/'contention.py',
              models/'design.ngspice', models/'sm141064.ngspice']
    before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in inputs}
    receipt = dict(status='running', physical_qualification=False,
        parasitics='Magic nominal distributed RC; not min/max RC',
        rc_audit=audit, inputs_sha256={str(p): sha(p) for p in inputs},
        excluded=['standalone schematic filter DC', 'Monte Carlo', 'noise',
                  'aging', 'supply collapse', 'maximum contention resolution'], cases=[])
    (out/'report.json').write_text(json.dumps(receipt, indent=2)+'\n')
    cases = [c for c in inventory() if args.campaign=='all' or
        ((c['kind'].startswith('reset') or c.get('reverse',False)) == (args.campaign=='supplement'))]
    # One paired half-step check on the fastest, asymmetrically loaded handover.
    convergence = next(c for c in cases if c['kind']=='sequence' and
        c['corner'][0]=='ff_n40C_3v60' and c['loads']==(.05,.005) and c['slews']==(.05,.05))
    cases.append(convergence | {'half_step': True})

    def run(index, case):
        folder = out/f'{index:03d}-{case["kind"]}-{case["corner"][0]}'
        folder.mkdir()
        wave, path, log = (folder/n for n in ('wave.tsv', 'probe.spice', 'simulation.log'))
        text, finish, step = deck(case, models, circuit, wave, .5 if case.get('half_step') else 1)
        path.write_text(text)
        result = case | {'index': index, 'maximum_step_ns': step, 'errors': []}
        command = [str(exe), '-n', '-b', str(path)]
        result['command'] = command
        try:
            with log.open('w') as stream:
                process = subprocess.run(command, cwd=models, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=args.timeout)
            result['returncode'] = process.returncode
            if process.returncode or not wave.is_file():
                raise ValueError('MUTEX_SPICE_EXECUTION_FAILED')
            names, rows = data(wave)
            validate_transient(names, rows, finish, step, columns=COLUMNS)
            result.update(analyze(rows,case))
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            result['errors'].append(str(error))
        result['passed'] = not result['errors']
        result['outputs_sha256'] = {str(p): sha(p) for p in (path, log, wave) if p.is_file()}
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run, i, c) for i, c in enumerate(cases)]
        for f in as_completed(futures):
            result = f.result()
            receipt['cases'].append(result)
            print(result['index'], result['passed'], result['errors'], flush=True)
            (out/'report.json').write_text(json.dumps(receipt, indent=2)+'\n')
    receipt['cases'].sort(key=lambda c: c['index'])
    coarse = next(c for c in receipt['cases'] if c['kind']=='sequence' and
        c['corner']==convergence['corner'] and c['loads']==convergence['loads'] and
        c['slews']==convergence['slews'] and c.get('reverse',False)==convergence.get('reverse',False) and not c.get('half_step'))
    fine = receipt['cases'][-1]
    metrics = ['uncontended_to_vih_ns','release0_to_vil_ns', 'release1_to_vil_ns', 'quiet_vil_to_vih_ns']
    delta = {k: abs(coarse[k]-fine[k]) for k in metrics if k in coarse and k in fine}
    receipt['half_step_max_delta_ns'] = max(delta.values()) if len(delta)==len(metrics) else None
    converged = len(delta)==len(metrics) and max(delta.values()) <= .005
    receipt['unchanged_inputs'] = all(p.is_file() and (p.stat().st_size,p.stat().st_mtime_ns)==before[str(p)] for p in inputs)
    receipt['status'] = 'pass' if converged and receipt['unchanged_inputs'] and all(c['passed'] for c in receipt['cases']) else 'fail'
    (out/'report.json').write_text(json.dumps(receipt, indent=2)+'\n')
    raise SystemExit(0 if receipt['status']=='pass' else 1)


if __name__ == '__main__':
    main()
