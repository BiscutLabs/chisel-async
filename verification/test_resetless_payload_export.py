# SPDX-License-Identifier: Apache-2.0
"""Resetless payload still requires complete endpoint and native-model checks."""
import json
from pathlib import Path
import shutil
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_export import validate_export, validate_manifest, semantic_hash


def export():
    candidates=list((ROOT/'build/resetless-payload').glob('export-*/simulation/contract.json'))
    assert candidates, 'Run ResetlessPayloadSpec before export tests'
    return max(candidates,key=lambda p:p.stat().st_mtime).parent


def test_resetless_export_runs_all_mapping_probes(tmp_path):
    directory=tmp_path/'resetless export'
    shutil.copytree(export(),directory)
    result=validate_export(directory)
    assert result['status']=='PASS' and result['mapping_checks']>0
    assert result['endpoints']


def test_resetless_model_cannot_hide_reset_or_initial_value():
    for field in ('port','parameter'):
        document=json.loads((export()/'contract.json').read_text())
        cell=next(p for p in document['manifest']['design']['primitives'] if p['id']=='payload')
        if field=='port':cell['ports'].append(dict(name='reset',width=1,direction='input'))
        else:cell['parameters']['RESET_VALUE']='0'
        document['semantic_sha256']=semantic_hash(document['manifest'])
        with pytest.raises(ValueError,match='^RESETLESS_PAYLOAD_'+('PORTS' if field=='port' else 'PARAMETERS')+'$'):
            validate_manifest(document)
