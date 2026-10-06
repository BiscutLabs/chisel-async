# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import shutil
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from check_export import validate_export
from test_export import edit_manifest


@pytest.mark.parametrize("fixture,key,value,diagnostic", [
    ("dualrail","phases",["rising-edge-fire"],"INVALID_CHANNEL"),
    ("to_async","clock","absent","MISSING_CHANNEL_ENDPOINT"),
    ("to_clocked","clock","out_data","CHANNEL_ENDPOINT_ASSOCIATION"),
    ("dualrail","zero","in_acknowledge","CHANNEL_ENDPOINT_ASSOCIATION"),
    ("dualrail","token_contract","unordered","INVALID_CHANNEL"),
])
def test_encoding_contract_cannot_be_relabelled(tmp_path,fixture,key,value,diagnostic):
    directory=tmp_path/fixture
    shutil.copytree(ROOT/'target/generated'/fixture,directory)
    def change(manifest):
        channels=manifest['design']['channels']
        channel=next(c for c in channels if c['protocol']!='four-phase-bundled-v1')
        channel[key]=value
    edit_manifest(directory,change)
    with pytest.raises(ValueError,match=f"^{diagnostic}$"):
        validate_export(directory)


def test_clock_anchor_rewiring_is_detected_after_rehash(tmp_path):
    directory=tmp_path/'clocked'
    shutil.copytree(ROOT/'target/generated/to_async',directory)
    path=directory/'ref_ToAsyncExample.sv'
    source=path.read_text()
    assert source.count('ca_p_8_in_clock packed_3_probe')==1
    path.write_text(source.replace('ca_p_8_in_clock packed_3_probe','ca_p_8_in_clock reset'))
    edit_manifest(directory,lambda _:None,refresh_rtl=True)
    with pytest.raises(ValueError,match='ENDPOINT_MAPPING_MISMATCH'):
        validate_export(directory)
