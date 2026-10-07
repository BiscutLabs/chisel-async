"""Negative controls for optional technology preparation and simulator setup."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from setup_simulator import checked_download

spec=importlib.util.spec_from_file_location('gf180_prepare',ROOT/'integrations/gf180/prepare.py')
gf180=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gf180)


def entry(model,params,ports,instance='stage.cell'):
    return dict(cell=dict(model=model,parameters={k:str(v) for k,v in params.items()}),
                ports=[dict(name=n,width=w,direction=d) for n,w,d in ports],instances=[instance])


def test_download_rejects_changed_cached_bytes(tmp_path):
    archive=tmp_path/'package'; archive.write_bytes(b'corrupt')
    with pytest.raises(RuntimeError,match='SIMULATOR_DOWNLOAD_CHECKSUM'):
        checked_download('https://invalid.example/unused',archive,'0'*64)


def test_reference_never_substitutes_boolean_feedback_for_a_c_element(tmp_path):
    required=tmp_path/'required.json'
    required.write_text(json.dumps([entry('ChiselAsyncAsymmetricC_v1',{'COMMON':1},[])]))
    lib=tmp_path/'cells.lib'; lib.write_text('cell(gf180mcu_fd_sc_mcu7t5v0__buf_1) {}')
    result=gf180.prepare(required,lib,tmp_path/'result',64)
    assert result['status']=='PARTIAL_REFERENCE' and len(result['missing'])==1
    assert not result['adapters']


def test_latch_reset_and_transparency_are_mapped_explicitly():
    cell=entry('ChiselAsyncClosingLatch_v1',{'WIDTH':2,'DELAY_FS':1000},
               [('reset',1,'input'),('closed',1,'input'),('d',2,'input'),('q',2,'output')])
    result,reason=gf180.adapter(cell,'TestLatch',None)
    assert reason is None
    source,cells,note=result
    assert source.count('__latrnq_1 ')==2
    assert '.I(closed), .ZN(enable)' in source and '.I(reset), .ZN(rn)' in source
    assert '.E(enable)' in source and '.RN(rn)' in source and '#' not in source


def test_trial_chain_requires_explicit_sizing_and_does_not_duplicate_data_budget():
    cell=entry('ChiselAsyncControlGate_v1',{'WIDTH':1,'OP':0,'RESET_VALUE':0,'DELAY_FS':11000000},
               [('reset',1,'input'),('a',1,'input'),('b',1,'input'),('q',1,'output')], 'stage.request_delay')
    assert gf180.adapter(cell,'Delay',None)[0] is None
    result,reason=gf180.adapter(cell,'Delay',3)
    assert reason is None and result[0].count('__buf_1 ')==3
    cell['instances']=['stage.data_delay']
    assert gf180.adapter(cell,'Delay',3)[0] is None


def test_missing_liberty_cell_is_not_an_available_adapter(tmp_path):
    cell=entry('ChiselAsyncClosingLatch_v1',{'WIDTH':1,'DELAY_FS':1000},
               [('reset',1,'input'),('closed',1,'input'),('d',1,'input'),('q',1,'output')])
    required=tmp_path/'required.json'; required.write_text(json.dumps([cell]))
    lib=tmp_path/'cells.lib'; lib.write_text('cell(gf180mcu_fd_sc_mcu7t5v0__inv_1) {}')
    result=gf180.prepare(required,lib,tmp_path/'result')
    assert not result['adapters'] and 'LIBERTY_CELL_MISSING' in result['missing'][0]['reason']
