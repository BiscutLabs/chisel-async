# SPDX-License-Identifier: Apache-2.0
import copy
import itertools
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest
from phase_reference import Protocol, Ledger, replay
from run_phase import delay_overrides, main
from phase_faults import replace_once, bypass_pin
from test_export import edit_manifest
from check_export import validate_export, nodes
from test_model_import import importer

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('start',(0,1))
@pytest.mark.parametrize('data',(0,255,17))
def test_two_phase_both_completion_edges_and_equal_payloads(start,data):
    p=Protocol('two-phase-bundled-v1',8)
    if start:
        p.observe(1,0,3);p.observe(1,1,3)
    for _ in range(4):
        request=1-p.req
        assert p.observe(request,p.ack,data)==[('offer',data)]
        assert p.observe(request,request,data)==[('complete',data),('return',data)]
    assert p.idle() and all(p.completion_polarities[v]>=2 for v in (0,1))
    p.reset();assert p.req==p.ack==0 and p.idle()


@pytest.mark.parametrize('edges,diagnostic', [
    ([(0,1,0)],'TWO_PHASE_ORDER'), ([(1,1,0)],'TWO_PHASE_ORDER'),
    ([(1,0,1),(0,0,1)],'TWO_PHASE_ORDER'), ([(1,0,1),(1,0,2)],'DATA_HOLD'),
    ([(1,0,1),(1,1,1),(0,1,7),(0,1,8)],'DATA_HOLD')])
def test_two_phase_checker_rejects_bad_parity_and_hold(edges,diagnostic):
    p=Protocol('two-phase-bundled-v1',8)
    with pytest.raises(AssertionError,match='^'+diagnostic+'$'):
        for edge in edges: p.observe(*edge)


def test_four_phase_holds_after_acceptance_until_full_return():
    p=Protocol('four-phase-bundled-v1',8)
    p.observe(1,0,7);p.observe(1,1,7);p.observe(0,1,7)
    with pytest.raises(AssertionError,match='DATA_HOLD'): p.observe(0,1,8)
    # A zero-delay mux can expose idle data in the same settled sample as ack fall.
    assert p.observe(0,0,8)==[('return',7)]


@pytest.mark.parametrize('polarity',(0,1))
def test_two_phase_idle_update_in_completion_sample_retains_original_token(polarity):
    p=Protocol('two-phase-bundled-v1',8)
    if polarity==0: p.observe(1,0,9);p.observe(1,1,9)
    p.observe(polarity,1-polarity,7)
    assert p.observe(polarity,polarity,8)==[('complete',7),('return',7)]
    assert p.idle()


def test_all_small_rail_values_and_valid_spacer_arrival_orders():
    checked=0
    for value in range(8):
        for up,down in itertools.product(itertools.permutations(range(3)),repeat=2):
            p=Protocol('dual-rail-rtz-v1',3);z=o=0;events=[]
            for bit in up:
                if value & (1<<bit): o|=1<<bit
                else: z|=1<<bit
                events+=p.observe(0,0,o,z)
            assert events==[('offer',value)]
            assert p.observe(0,1,o,z)==[('complete',value)]
            for bit in down:
                o&=~(1<<bit);z&=~(1<<bit)
                assert not p.observe(0,1,o,z)
            assert p.observe(0,0,0,0)==[('return',value)] and p.idle()
            checked+=1
    assert checked==288


@pytest.mark.parametrize('bad,diagnostic', [('overlap','INVALID_RAIL'),('early_ack','RAIL_EARLY_ACK'),
    ('early_spacer','RAIL_EARLY_SPACER'),('withdraw','RAIL_ORDER')])
def test_rail_monitor_rejects_incomplete_and_nonmonotonic_phases(bad,diagnostic):
    p=Protocol('dual-rail-rtz-v1',3)
    with pytest.raises(AssertionError,match='^'+diagnostic+'$'):
        if bad=='overlap': p.observe(0,0,1,1)
        elif bad=='early_ack': p.observe(0,1,1,0)
        elif bad=='withdraw': p.observe(0,0,1,0);p.observe(0,0,0,0)
        else:
            p.observe(0,0,7,0);p.observe(0,1,7,0);p.observe(0,0,6,0)


def channel(name,role):
    return dict(id=name,role=role,protocol='two-phase-bundled-v1',layout=[dict(field='bits',lsb=0,width=8)])


@pytest.mark.parametrize('winner',('in0','in1'))
def test_arbitration_ledger_allows_either_winner_but_preserves_each_stream(winner):
    model=Ledger('two_arbiter',[channel('in0','input'),channel('in1','input'),channel('out','output')])
    values={'in0':17,'in1':81}
    for name,value in values.items(): model.observe(False,name,1,0,value,0)
    model.observe(False,'out',1,0,values[winner],0);model.observe(False,'out',1,1,values[winner],0)
    assert not model.queues[winner]
    loser='in1' if winner=='in0' else 'in0'
    assert list(model.queues[loser])==[values[loser]]
    with pytest.raises(AssertionError,match='ARBITRATION_PAYLOAD'): model.observe(False,'out',0,1,99,0)


@pytest.mark.parametrize('fixture,kind', [('phase_to_four','phase-conversion-v2'),
    ('phase_to_two','phase-conversion-v2'),('encoding_to_dual','encoding-boundary-v1'),
    ('encoding_from_dual','encoding-boundary-v1')])
def test_phase_and_encoding_constraints_survive_optimized_export(fixture,kind):
    path=ROOT/'target/generated'/fixture
    assert validate_export(path)['status']=='PASS'
    m=json.loads((path/'contract.json').read_text(encoding='utf-8'))['manifest']
    constraints=[t for n in nodes(m['design']) for t in n['timing'] if t['kind']==kind]
    assert len(constraints)==1
    assert constraints[0]['cells']==dict(min_fs='1000000',max_fs='10000000',model_fs='1000000')
    assert not any(p['clock'] for n in json.loads((path/'ports.json').read_text())['nodes'] for p in n['ports'])


@pytest.mark.parametrize('fault,diagnostic', [('missing','MISSING_PHASE_CONSTRAINT'),
    ('guard','INVALID_PHASE_RETURN_GUARD'),('model','PHASE_PARAMETER_MISMATCH'),
    ('direction','INVALID_PHASE_DIRECTION'),('endpoint','INVALID_PHASE_BINDING')])
def test_rehashed_phase_constraint_corruption_fails(tmp_path,fault,diagnostic):
    directory=tmp_path/'phase';shutil.copytree(ROOT/'target/generated/phase_to_four',directory)
    def corrupt(m):
        n=next(c['contract'] for c in m['design']['children'] if c['id']=='adapter');t=n['timing'][0]
        if fault=='missing': n['timing']=[]
        elif fault=='guard': t['return_delay_fs']=t['cells']['max_fs']
        elif fault=='model': t['cells']['model_fs']='2000000'
        elif fault=='direction': t['direction']='four-to-two'
        else: t['input_request']='out_request'
    edit_manifest(directory,corrupt)
    with pytest.raises(ValueError,match='^'+diagnostic+'$'): validate_export(directory)


@pytest.mark.parametrize('fault,diagnostic', [('missing','MISSING_ENCODING_CONSTRAINT'),
    ('guard','INVALID_ENCODING_GUARD'),('budget','ENCODING_BUDGET_MISMATCH'),
    ('model','ENCODING_PARAMETER_MISMATCH'),('endpoint','INVALID_ENCODING_BINDING')])
def test_rehashed_encoding_constraint_corruption_fails(tmp_path,fault,diagnostic):
    directory=tmp_path/'encoding';shutil.copytree(ROOT/'target/generated/encoding_from_dual',directory)
    def corrupt(m):
        n=m['design'];t=n['timing'][0]
        if fault=='missing': n['timing']=[]
        elif fault=='guard': t['return_delay_fs']=t['cells']['max_fs']
        elif fault=='budget': t['data_delay']['max_fs']='9000000'
        elif fault=='model': t['cells']['model_fs']='2000000'
        else: t['output_data']='in_one'
    edit_manifest(directory,corrupt)
    with pytest.raises(ValueError,match='^'+diagnostic+'$'): validate_export(directory)


@pytest.mark.parametrize('fixture,identity',[('phase_to_four','master_close'),
    ('phase_to_two','request_phase'),('encoding_from_dual','decoded'),('encoding_to_dual','zero0')])
def test_renamed_cells_cannot_hide_deleted_timing_obligations(tmp_path,fixture,identity):
    directory=tmp_path/fixture;shutil.copytree(ROOT/'target/generated'/fixture,directory)
    def corrupt(m):
        n=next(n for n in nodes(m['design']) if any(p['id']==identity for p in n['primitives']))
        n['timing']=[]
        next(p for p in n['primitives'] if p['id']==identity)['id']='renamed_cell'
    edit_manifest(directory,corrupt)
    with pytest.raises(ValueError,match='^TIMING_MARKER_INVENTORY$'): validate_export(directory)


@pytest.mark.parametrize('fixture',('two_buffer','buffer','two_fork'))
def test_bundled_protocol_label_is_bound_to_actual_chisel_type(tmp_path,fixture):
    directory=tmp_path/fixture;shutil.copytree(ROOT/'target/generated'/fixture,directory)
    def corrupt(m):
        c=m['design']['channels'][0]
        c['protocol']='four-phase-bundled-v1' if c['protocol']=='two-phase-bundled-v1' else 'two-phase-bundled-v1'
    edit_manifest(directory,corrupt)
    with pytest.raises(ValueError,match='^CHANNEL_PROTOCOL_MISMATCH$'): validate_export(directory)


def test_independent_cell_sweep_rejects_narrowed_adapter_bounds():
    m=json.loads((ROOT/'target/generated/phase_to_four/contract.json').read_text())['manifest']
    n=next(c['contract'] for c in m['design']['children'] if c['id']=='adapter')
    n['timing'][0]['cells']['max_fs']='1000000'
    with pytest.raises(AssertionError,match='OVERRIDE_OUTSIDE_POLICY'): delay_overrides(m,2)


def test_empty_fault_selection_cannot_reuse_success(tmp_path,monkeypatch):
    (tmp_path/'report.json').write_text('{"status":"PASS"}')
    monkeypatch.setattr(sys,'argv',['run_phase.py','--fixtures','two_wide','--faults-only','--output',str(tmp_path)])
    with pytest.raises(AssertionError,match='EMPTY_PHASE_CAMPAIGN'): main()
    assert json.loads((tmp_path/'report.json').read_text())['status']=='ERROR'


def test_mutations_require_actual_targets():
    with pytest.raises(AssertionError,match='FAULT_TARGET_COUNT'): replace_once('absent','missing','new')
    with pytest.raises(AssertionError,match='FAULT_PIN_TARGET'): bypass_pin('module empty; endmodule','missing','0',1)


@pytest.mark.parametrize('omit_internal',('none','all','last_epoch','missing_witness','wrong_count'))
def test_trace_cannot_silently_omit_an_internal_boundary(tmp_path,omit_internal):
    channels=[dict(channel(n,r),protocol='four-phase-bundled-v1')
              for n,r in [('in','input'),('middle','internal'),('out','output')]]
    lines=['PHASE_TRACE|2']
    def event(name,req,ack,data,reset=0):
        if name!='middle' or omit_internal!='all' and not (omit_internal=='last_epoch' and epoch==2):
            lines.append(f'{len(lines)}|{reset}|{name}|{req}|{ack}|{data:x}|0')
    for epoch in range(3):
        event('in',0,0,0,reset=1)
        event('in',0,0,0)
        event('in',1,0,7)
        if epoch!=1:  # One offered, undelivered token is reset-aborted.
            for name in ('middle','out'):
                for req,ack in ((1,0),(1,1),(0,1),(0,0)): event(name,req,ack,7)
            for req,ack in ((1,1),(0,1),(0,0)): event('in',req,ack,7)
        for name in ('in','middle','out'):
            if omit_internal=='missing_witness' and name=='middle': continue
            count=9 if omit_internal=='wrong_count' and name=='middle' else int(epoch!=1)
            lines.append(f'COUNTS|{epoch+1}|{name}|{count}')
    path=tmp_path/'trace.txt';path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if omit_internal!='none':
        diagnostic={'all':'MISSING_CHANNEL_ACTIVITY','missing_witness':'MISSING_COMPLETION_WITNESS'}.get(omit_internal,'CHANNEL_COMPLETION_MISMATCH')
        with pytest.raises(AssertionError,match=diagnostic): replay('phase_roundtrip',channels,path)
    else:
        assert replay('phase_roundtrip',channels,path)['delivered']==2


@pytest.mark.parametrize('model,parameter',[('ChiselAsyncXor_v1','DELAY_FS'),
    ('ChiselAsyncToggle_v1','DELAY_FS'),('ChiselAsyncMutex_v1','RESOLVE_FS')])
def test_new_models_enter_actual_circt_flow(tmp_path,model,parameter):
    source=ROOT/'src/main/resources/chiselasync/sv'/(model+'.sv');output=tmp_path/'model.mlir'
    result=subprocess.run([importer(),'--top',model,'-G',parameter+'=1000000',str(source),'-o',str(output)],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    text=output.read_text()
    assert f'hw.module @{model}' in text and 'llhd.delay' in text and 'by <1000000fs, 0d, 0e>' in text


@pytest.mark.parametrize('policy',(0,1,2))
@pytest.mark.parametrize('delay',(1,3,10))
def test_mutex_collision_policy_persistence_handover_and_reset(tmp_path,policy,delay):
    source=ROOT/'src/main/resources/chiselasync/sv/ChiselAsyncMutex_v1.sv'
    bench=tmp_path/'bench.sv'
    bench.write_text(f'''module MutexBench;
timeunit 1ns; timeprecision 1ps;
reg reset; reg [1:0] request=0; wire [1:0] grant;
integer round, expected, count=0;
ChiselAsyncMutex_v1 #(.RESOLVE_FS({delay*1000000}),.POLICY({policy})) dut(reset,request,grant);
always @(grant) if (!reset) begin
  if (grant === 2'b11 || $isunknown(grant)) $fatal(1,"GRANT_EXCLUSION");
  if (grant != 0) count=count+1;
end
initial begin
  reset=1;
  #{delay*3}; reset=0;
  for (round=0; round<4; round=round+1) begin
    request=3;
    expected=({policy}==1 || ({policy}==2 && round%2==1)) ? 2 : 1;
    #{delay*3};
    if (grant !== expected) $fatal(1,"COLLISION_POLICY");
    // A losing request may leave/re-enter without revoking the held winner.
    request=expected; #{delay*3}; request=3; #{delay*3};
    if (grant !== expected) $fatal(1,"WINNER_NOT_PERSISTENT");
    request=0; #{delay*3};
    if (grant !== 0) $fatal(1,"RELEASE");
  end
  request=1; #{delay*3}; request=3; #{delay*3}; request=2;
  #{delay/2}; if (grant !== 1) $fatal(1,"EARLY_RELEASE");
  #{delay}; if (grant !== 0) $fatal(1,"MISSING_RETURN_INTERLOCK");
  #{delay*2}; if (grant !== 2) $fatal(1,"PENDING_REQUEST_LOST");
  reset=1; request=0; #{delay*3};
  if (grant !== 0 || count != 6) $fatal(1,"RESET_OR_ACTIVITY");
  reset=0; request=3; #{delay*3};
  if (grant !== ({policy}==1 ? 2 : 1)) $fatal(1,"RESET_POLICY");
  $display("MUTEX_PASS"); $finish;
end
initial begin #10000; $fatal(1,"PROGRESS_DEADLINE"); end
endmodule
''',encoding='utf-8')
    result=subprocess.run(['iverilog','-g2012','-s','MutexBench','-o',str(tmp_path/'sim'),str(bench),str(source)],
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    result=subprocess.run(['vvp',str(tmp_path/'sim')],capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and result.stdout.splitlines().count('MUTEX_PASS')==1,result.stdout+result.stderr
