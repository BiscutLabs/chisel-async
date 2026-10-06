# SPDX-License-Identifier: Apache-2.0
import json
import re
import shutil
import subprocess
import sys
import pytest
from run import ROOT, read_sources
from run_phase import validate_export, nodes, execute
from test_export import edit_manifest
from test_model_import import importer


@pytest.mark.parametrize('lane',('dims','closure','mutex','reference'))
def test_failed_new_campaign_cannot_leave_a_stale_pass(tmp_path,lane):
    out=tmp_path/'evidence';out.mkdir()
    (out/'report.json').write_text('{"status":"PASS","prior_run":true}',encoding='utf-8')
    result=subprocess.run([sys.executable,str(ROOT/f'verification/run_{lane}.py'),
        '--generated',str(tmp_path/'missing'),'--output',str(out)],capture_output=True,text=True,timeout=30)
    assert result.returncode!=0
    report=json.loads((out/'report.json').read_text(encoding='utf-8'))
    assert report['status'] in ('RUNNING','ERROR') and 'prior_run' not in report


@pytest.mark.parametrize('fault,diagnostic', [('equal','INVALID_PHASE_CLOSURE_GUARD'),
    ('missing','MISSING_PHASE_CLOSURE'),('model','PHASE_PARAMETER_MISMATCH')])
def test_history_closure_descriptor_rejects_unsound_budget(tmp_path,fault,diagnostic):
    dest=tmp_path/'export';shutil.copytree(ROOT/'target/generated/phase_to_two',dest)
    def change(m):
        t=next(t for n in nodes(m['design']) for t in n['timing'] if t['kind']=='phase-conversion-v2')
        if fault=='equal': t['request_delay_fs']=t['history_closure']['max_fs']
        elif fault=='missing':
            for key in ('history_closed','history_closure','request_delay_fs'): del t[key]
        else: t['history_closure']['model_fs']='2000000'
    edit_manifest(dest,change)
    with pytest.raises(ValueError,match='^'+diagnostic+'$'): validate_export(dest)


@pytest.mark.parametrize('cell,pin,value', [('history','closed',"1'b0"),
    ('request_guard','a','in_req'),('history_close','a','out_ack'),('request_phase','trigger','out_ack')])
def test_closure_constraint_is_bound_to_actual_pins(tmp_path,cell,pin,value):
    dest=tmp_path/'export';shutil.copytree(ROOT/'target/generated/phase_to_two',dest)
    m=json.loads((dest/'contract.json').read_text(encoding='utf-8'))['manifest']
    node=next(n for n in nodes(m['design']) if any(p['id']=='history' for p in n['primitives']))
    instance=next(p for p in node['primitives'] if p['id']==cell)['rtl_path'].split('.')[-1]
    source=dest/(node['module']+'.sv')
    text,n=re.subn('('+re.escape(instance)+r'\s*\([\s\S]*?\.'+pin+r'\s*\()[^)]*(\))',
                  lambda x:x[1]+value+x[2],source.read_text(encoding='utf-8'));assert n==1
    source.write_text(text,encoding='utf-8')
    edit_manifest(dest,lambda m:None,refresh_rtl=True)
    with pytest.raises(ValueError,match='^PHASE_CLOSURE_BINDING_MISMATCH$'): validate_export(dest)


@pytest.mark.parametrize('parameter,value',[('OP','1'),('WIDTH','2'),('RESET_VALUE','1')])
def test_guard_requires_an_actual_noninverting_buffer(tmp_path,parameter,value):
    dest=tmp_path/'export';shutil.copytree(ROOT/'target/generated/phase_to_two',dest)
    def change(m):
        p=next(p for n in nodes(m['design']) for p in n['primitives'] if p['id']=='request_guard')
        p['parameters'][parameter]=value
    edit_manifest(dest,change)
    with pytest.raises(ValueError,match='^PHASE_GUARD_CELL_MISMATCH$'): validate_export(dest)


def test_maximum_campaign_seed_runs_random_arbitration(tmp_path):
    generated=ROOT/'target/generated/arbiter'
    m=json.loads((generated/'contract.json').read_text(encoding='utf-8'))['manifest']
    ports=json.loads((generated/'ports.json').read_text(encoding='utf-8'))['nodes'][0]['ports']
    result=execute('arbiter',0xffffffff,tmp_path,m,ports,read_sources(generated))
    assert result['status']=='PASS' and any('.SEED=1;' in value for value in result['overrides'])


def test_random_mutex_import_keeps_dynamic_delay(tmp_path):
    output=tmp_path/'model.mlir'
    command=[importer(),'--top','ChiselAsyncMutex_v1','-G','POLICY=3','-G','SEED=123',
             '-G','RESOLVE_FS=1000000','-G','RESOLVE_MAX_FS=20000000',
             str(ROOT/'src/main/resources/chiselasync/sv/ChiselAsyncMutex_v1.sv'),'-o',str(output)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    ir=output.read_text(encoding='utf-8')
    assert 'hw.module @ChiselAsyncMutex_v1' in ir and 'llhd' in ir and 'ticket' in ir


@pytest.mark.parametrize('change,old_grant', [('#10;request=2;',0),('#10;#0;request=2;',0),
    ('#10;request<=2;',0),('request<=#10 2;#10;',0),('#9;request=2;#1;',0),
    ('#11;request=2;',1),('#10;reset=1;request=0;',0),
    ('#10;reset<=1;request<=0;',0),('reset<=#10 1;request<=#10 0;#10;',0)])
def test_mutex_resolution_boundary_cancels_stale_ticket(tmp_path,change,old_grant):
    bench=tmp_path/'bench.sv';bench.write_text(f'''module Boundary;
timeunit 1fs;timeprecision 1fs;
reg reset=0;reg [1:0] request=0;wire [1:0] grant;
ChiselAsyncMutex_v1 #(.POLICY(3),.RESOLVE_FS(10),.RESOLVE_MAX_FS(10),.SEED(1)) dut(reset,request,grant);
initial begin reset=1;#5;reset=0;#15;request=1;{change}
#1;if(grant !== 2'd{old_grant}) $fatal(1,"STALE_DECISION");
#40;if(grant !== (reset ? 0 : 2)) $fatal(1,"LOST_RESTART");
$display("BOUNDARY_PASS");$finish;end endmodule
''',encoding='utf-8')
    result=subprocess.run(['iverilog','-g2012','-s','Boundary','-o',str(tmp_path/'sim'),str(bench),
        str(ROOT/'src/main/resources/chiselasync/sv/ChiselAsyncMutex_v1.sv')],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    result=subprocess.run(['vvp',str(tmp_path/'sim')],capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and result.stdout.splitlines().count('BOUNDARY_PASS')==1,result.stdout+result.stderr
