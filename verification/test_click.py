# SPDX-License-Identifier: Apache-2.0
"""Native Click export, independent ring oracle, fault controls and CIRCT import."""
import copy
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_export import nodes, validate_export, validate_manifest, semantic_hash
from run import read_sources
from test_export import edit_manifest
from test_model_import import importer

def fixture(name):
    path = ROOT / 'target/generated' / ('click_' + name)
    assert (path/'contract.json').is_file(), 'Run examples/runMain chiselasync.examples.EmitClick target/generated'
    return path


@pytest.mark.parametrize('name', ('standard','decoupled','seeded','fifo','decoupled_fifo','ring'))
def test_click_optimized_export_matches_actual_wiring(name):
    result = validate_export(fixture(name))
    assert result['status'] == 'PASS' and result['mapping_checks'] > 1000


@pytest.mark.parametrize('fault,code', [
    ('missing','MISSING_CLICK_CONSTRAINT'),('short-pulse','CLICK_HIGH_PULSE_BOUND'),
    ('early-data','CLICK_DATA_GUARD'),('early-ack','CLICK_ACK_GUARD'),
    ('early-output','CLICK_OUTPUT_GUARD'),('cell','CLICK_CELL_PARAMETERS'),
    ('marker','TIMING_MARKER_PARAMETER_MISMATCH'),('variant','CLICK_INITIALIZATION')])
def test_click_contract_mutations_fail_for_specific_reasons(fault,code):
    doc=copy.deepcopy(json.loads((fixture('seeded')/'contract.json').read_text()))
    node=doc['manifest']['design']; t=node['timing'][0]
    if fault=='missing': node['timing']=[]
    elif fault=='short-pulse': t['times']['PULSE_HIGH_FS']='2900000'
    elif fault=='early-data': t['times']['REQUEST_FS']='10100000'
    elif fault=='early-ack': t['times']['ACKNOWLEDGE_FS']='30200000'
    elif fault=='early-output': t['times']['OUTPUT_FS']='30200000'
    elif fault=='cell': next(p for p in node['primitives'] if p['id']=='input_phase')['parameters']['RESET_VALUE']='1'
    elif fault=='marker': next(p for p in node['primitives'] if p['view']=='constraint-marker')['parameters']['CLOCK_SKEW_FS']='0'
    elif fault=='variant': t['variant']='standard'
    doc['semantic_sha256']=semantic_hash(doc['manifest'])
    with pytest.raises(ValueError,match='^'+code+'$'): validate_manifest(doc)


def test_shared_phase_short_feedback_is_not_hidden_by_asymmetric_bounds():
    doc=copy.deepcopy(json.loads((fixture('standard')/'contract.json').read_text()))
    t=doc['manifest']['design']['timing'][0]
    for role,delay in (('input_phase',1000000),('output_phase',10000000),
                       ('input_compare',10000000),('output_compare',1000000)):
        t['cells'][role]={k:str(delay) for k in ('min_fs','max_fs','model_fs')}
    t['times']['PULSE_HIGH_FS']='3000000'
    doc['semantic_sha256']=semantic_hash(doc['manifest'])
    with pytest.raises(ValueError,match='^CLICK_HIGH_PULSE_BOUND$'): validate_manifest(doc)


def test_click_pulse_miswiring_is_detected_after_rehash(tmp_path):
    dest=tmp_path/'fault'; shutil.copytree(fixture('decoupled'),dest)
    doc=json.loads((dest/'contract.json').read_text()); node=doc['manifest']['design']
    path=dest/(node['module']+'.sv'); rtl=path.read_text()
    # Change one register's trigger to an unrelated phase while retaining inventory.
    pattern=r'(ca_primitive_output_phase\s*\([\s\S]*?\.trigger\s*\()([^)]*)(\))'
    rtl,n=re.subn(pattern,lambda m:m[1]+'ca_primitive_input_phase_q'+m[3],rtl,count=1)
    assert n==1
    path.write_text(rtl)
    edit_manifest(dest,lambda _:None,refresh_rtl=True)
    with pytest.raises(ValueError,match='^CLICK_BINDING_MISMATCH$'): validate_export(dest)


def ring_run(seed, directory, fault=None):
    directory.mkdir(parents=True,exist_ok=False)
    exported=fixture('ring')
    manifest=json.loads((exported/'contract.json').read_text())['manifest']
    rng=random.Random(seed); overrides=[]; delays={}
    for node in nodes(manifest['design']):
        policy=next((t for t in node['timing'] if t['kind']=='click-bundling-v1'),None)
        if not policy: continue
        for p in node['primitives']:
            role='fire' if p['id']=='start_barrier' else p['id']
            if role not in policy['cells']: continue
            b=policy['cells'][role]; lo=int(b['min_fs']); hi=int(b['max_fs'])
            delay=lo if seed==1 else hi if seed==2 else rng.randint(lo,hi)
            name='dut.'+p['rtl_path'].partition('.')[2]
            overrides.append(f'defparam {name}.DELAY_FS={delay};')
            delays[name]=delay
    if fault=='no-seed': overrides.append('defparam dut.ca_child_seed.ca_primitive_output_phase.RESET_VALUE=0;')
    resources=set(manifest['resources'])
    sources=[s for s in read_sources(exported) if s.name not in {Path(r).name for r in resources}]
    for resource in sorted(resources):
        text=(ROOT/'src/main/resources'/resource).read_text()
        if fault=='payload' and resource.endswith('EventRegister_v1.sv'):
            assert text.count('else state <= d;')==1
            text=text.replace('else state <= d;','else state <= (RESET_VALUE == 7) ? ~d : d;')
        target=directory/Path(resource).name; target.write_text(text); sources.append(target.resolve())
    tb='''module Testbench;
timeunit 1fs; timeprecision 1fs;
reg reset=0, start=0; wire tick; wire [7:0] value;
ClickRing dut(.reset(reset),.start(start),.tick(tick),.value(value));
OVERRIDES
integer count=0,total=0; reg last=0;
always @(tick or posedge reset) begin
  #1;
  if(reset) begin count=0; last=0; end
  else if(start && tick != last) begin
    if(value !== ((7+count)&255)) $fatal(1,"RING_PAYLOAD");
    $display("TOKEN %0d %0d %0d",$time,count,value);
    count=count+1; total=total+1; last=tick;
  end
end
initial begin
  repeat(2) begin
    reset=1; start=0; #1000000000; reset=0; #1000000000;
    if(count != 0 || tick !== 0) $fatal(1,"RING_START_BARRIER");
    start=1; wait(count==80); reset=1; #1000000000;
  end
  if(total != 160) $fatal(1,"RING_COUNT");
  $display("RING_PASS 160"); $finish;
end
initial begin #100000000000; $fatal(1,"RING_DEADLINE"); end
endmodule
'''.replace('OVERRIDES','\n'.join(overrides))
    (directory/'testbench.sv').write_text(tb)
    (directory/'delays.json').write_text(json.dumps({'seed':seed,'cells_fs':delays},indent=2))
    compile=subprocess.run(['iverilog','-g2012','-s','Testbench','-o','test.vvp',*[str(s) for s in sources],
                            'testbench.sv'],cwd=directory,text=True,capture_output=True,timeout=30)
    (directory/'compile.log').write_text(compile.stdout+compile.stderr)
    assert compile.returncode==0,compile.stderr
    run=subprocess.run(['vvp','test.vvp'],cwd=directory,text=True,capture_output=True,timeout=30)
    (directory/'simulation.log').write_text(run.stdout+run.stderr)
    if fault:
        code='RING_DEADLINE' if fault=='no-seed' else 'RING_PAYLOAD'
        assert run.returncode!=0 and re.findall(r'FATAL: .*?: ([A-Z_]+)',run.stdout)==[code],run.stdout+run.stderr
    else:
        assert run.returncode==0 and run.stdout.count('RING_PASS 160')==1,run.stdout+run.stderr
        tokens=[int(line.split()[3]) for line in run.stdout.splitlines() if line.startswith('TOKEN ')]
        assert tokens==list(range(7,87))*2
    (directory/'result.json').write_text(json.dumps({'status':'EXPECTED_FAILURE' if fault else 'PASS','seed':seed,
                                                   'tokens':0 if fault else 160,'fault':fault}))


@pytest.mark.parametrize('seed',range(1,301))
def test_click_one_token_ring_with_independent_cell_delays(tmp_path,seed):
    ring_run(seed,tmp_path/f'seed-{seed}')


@pytest.mark.parametrize('fault',('no-seed','payload'))
def test_click_ring_negative_controls(tmp_path,fault):
    ring_run(19,tmp_path/fault,fault)


@pytest.mark.parametrize('model',('ChiselAsyncEventRegister_v1','ChiselAsyncPhaseRegister_v1'))
def test_click_edge_register_models_import_with_delays(tmp_path,model):
    path=ROOT/'src/main/resources/chiselasync/sv'/(model+'.sv')
    output=tmp_path/'model.mlir'
    run=subprocess.run([importer(),'--top',model,'-G','DELAY_FS=1000',str(path),'-o',str(output)],
                       text=True,capture_output=True,timeout=30)
    assert run.returncode==0,run.stderr
    assert 'llhd.delay' in output.read_text() and '1000fs' in output.read_text()
