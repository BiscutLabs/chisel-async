# SPDX-License-Identifier: Apache-2.0
"""Hand-derived composition obligations and adversarial export coverage."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from composition_reference import CompositionLedger, replay
from run_composition import mutate, FIXTURES, FAULTS, port_roles
from test_export import edit_manifest
from check_export import validate_export

ROOT=Path(__file__).resolve().parents[1]


def offer(model, port, data): model.edge(port,'req',1,data)
def accept(model, port, data): model.edge(port,'ack',1,data)
def returned(model, port, data):
    model.edge(port,'req',0,data); model.edge(port,'ack',0,data)


def test_fifo_reserves_delivered_storage_until_return_and_reinstalls_initial_tokens():
    m=CompositionLedger('initialized_fifo',{'in':'input','out':'output'}); m.reset()
    offer(m,'out',0x12); accept(m,'out',0x12)
    offer(m,'in',77)
    with pytest.raises(AssertionError,match='CAPACITY_EXCEEDED'): accept(m,'in',77)
    m=CompositionLedger('initialized_fifo',{'in':'input','out':'output'}); m.reset()
    offer(m,'out',0x12); accept(m,'out',0x12); returned(m,'out',0x12)
    offer(m,'in',77); accept(m,'in',77); returned(m,'in',77)
    m.reset(); assert list(m.queue)==[0x12,0x12,0xe7]
    assert m.aborted==3 and m.delivered==1 and m.initialized==6
    m.check()


def test_fork_partial_delivery_survives_reset_and_requires_every_branch():
    roles={'in':'input',**{f'out_{i}':'output' for i in range(3)}}
    m=CompositionLedger('fork',roles); m.reset(); offer(m,'in',9)
    for p in ('out_0','out_1','out_2'): offer(m,p,9)
    accept(m,'out_0',9)
    with pytest.raises(AssertionError,match='FORK_EARLY_ACCEPT'): accept(m,'in',9)
    # Separate legal partial transaction, without retaining a rejected edge.
    m=CompositionLedger('fork',roles); m.reset(); offer(m,'in',9); offer(m,'out_0',9); accept(m,'out_0',9)
    m.reset(); m.check()
    assert m.by_port['out_0']==1 and m.fork_aborted=={'out_0':0,'out_1':1,'out_2':1}


def test_join_pairs_distinct_accepted_stream_positions():
    m=CompositionLedger('join',{'left':'input','right':'input','out':'output'}); m.reset()
    offer(m,'left',5); accept(m,'left',5); returned(m,'left',5)
    with pytest.raises(AssertionError,match='JOIN_MISSING_OPERAND'): m.expected('out')
    offer(m,'right',257); accept(m,'right',257)
    with pytest.raises(AssertionError,match='JOIN_PAIR'): offer(m,'out',(5,258))
    assert m.expected('out')==(5,257)


def test_selection_routes_once_and_trace_hold_rejects_recovered_excursions():
    m=CompositionLedger('select',{'in':'input','out_0':'output','out_1':'output'}); m.reset()
    offer(m,'in',(1,42)); accept(m,'in',(1,42)); returned(m,'in',(1,42))
    with pytest.raises(AssertionError,match='SELECT_ROUTE'): m.expected('out_0')
    assert m.expected('out_1')==42
    events=[dict(time_fs=0,kind='reset'),dict(time_fs=1,kind='edge',port='in',signal='req',value=1,payload=42),
            dict(time_fs=2,kind='data',port='in',payload=43),dict(time_fs=3,kind='data',port='in',payload=42)]
    with pytest.raises(AssertionError,match='COMPOSITION_DATA_HOLD'): replay('fifo',{'in':'input','out':'output'},events)


@pytest.mark.parametrize('fixture',FIXTURES)
def test_composition_exports_have_active_typed_mappings(fixture):
    directory=ROOT/'target/generated'/fixture
    result=validate_export(directory)
    assert result['status']=='PASS' and result['mapping_checks']>0 and port_roles(directory)


def test_mux_child_payload_alias_is_rejected_with_control_and_data_coactivation(tmp_path):
    directory=tmp_path/'merge'; shutil.copytree(ROOT/'target/generated/merge',directory)
    document=json.loads((directory/'contract.json').read_text())
    abi=directory/document['manifest']['probe_abi']['file']
    text=abi.read_text()
    # A same-width source alias in the child is independently checked against its
    # typed input port, and must remain detectable under optimized mux lowering.
    key='ca_p_7_storage_7_in_data'
    lines=[line for line in text.splitlines() if key in line]
    assert len(lines)==1
    old=lines[0]; new=old.rsplit(' ',1)[0]+' in_0_bits'
    abi.write_text(text.replace(old,new),encoding='utf-8')
    edit_manifest(directory,lambda m:None,refresh_rtl=True)
    with pytest.raises(ValueError,match='ENDPOINT_MAPPING_MISMATCH'): validate_export(directory)


def test_mutations_refuse_missing_targets():
    for name in FAULTS:
        if name not in ('merge_contention','merge_contention_return','invalid_select'):
            with pytest.raises(AssertionError,match='MUTATION_TARGET'): mutate('module absent; endmodule',name)


@pytest.mark.parametrize('delay',(1000,10000000))
def test_atomic_and_and_sticky_initialization_cells_against_truth_and_history(tmp_path,delay):
    # AND checks all polarities; the initialized source's new sticky configuration
    # checks every three-vector history, including reset after completion.
    import itertools
    lines=[]; checks=0
    for mask in (0,2):
        for history in itertools.product(range(4),repeat=3):
            lines.append(f'reset=1; mask={mask}; d=0; #(D+1); reset=0;')
            previous=0
            for value in history:
                want=int((value^mask)==3); previous=previous or want
                lines.append(f'd={value}; #(D+1); if(a!==1\'b{want} || c!==1\'b{int(previous)}) $fatal(1,"COMPOSITION_CELL_ORACLE");')
                checks+=1
    bench=f'''module Bench; timeunit 1fs; timeprecision 1fs;
parameter D={delay}; reg reset=0; reg [1:0] d=0,mask=0; wire a,c;
ChiselAsyncAnd_v1 #(.DELAY_FS(D)) gate0(.reset(reset),.d(d^mask),.q(a));
ChiselAsyncAsymmetricC_v1 #(.COMMON(1),.RISING(2),.FALLING(0),.DELAY_FS(D)) state0(
 .reset(reset),.common(1'b1),.rising(d^mask),.falling(1'b0),.q(c));
initial begin #1; {''.join(lines)} $display("CELL_PASS:{checks}"); $finish; end
initial begin #100000000000; $fatal(1,"CELL_TIMEOUT"); end endmodule'''
    source=tmp_path/'bench.sv'; source.write_text(bench,encoding='utf-8')
    models=ROOT/'src/main/resources/chiselasync/sv'
    image=tmp_path/'test.vvp'
    subprocess.run(['iverilog','-g2012','-s','Bench','-o',str(image),str(source),
                    str(models/'ChiselAsyncAnd_v1.sv'),str(models/'ChiselAsyncAsymmetricC_v1.sv')],check=True,capture_output=True,timeout=30)
    result=subprocess.run(['vvp',str(image)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0 and result.stdout.splitlines().count(f'CELL_PASS:{checks}')==1,result.stdout
