# SPDX-License-Identifier: Apache-2.0
"""Prepare experimental GF180 7-track adapters and a complete missing-cell inventory.

Consumes AsicMapping's required-cells.json. Does not install a PDK or invent
implementations for state-holding control. A partial plan never exits successfully.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

PREFIX = "gf180mcu_fd_sc_mcu7t5v0__"


def adapter(required, name, stages):
    key = required["cell"]
    params = {k: int(v) for k, v in key["parameters"].items()}
    model = key["model"]
    width = params.get("WIDTH", 1)
    ports = required["ports"]
    header = f'module {name} (' + ', '.join(
        f'{p["direction"]} wire [{p["width"]-1}:0] {p["name"]}' for p in ports) + ');\n'
    cells = []
    def cell(kind, instance, **pins):
        cells.append(kind)
        return f'  (* dont_touch = "yes", keep = "yes" *) {PREFIX}{kind} {instance} (' + ', '.join(f'.{p}({v})' for p,v in pins.items()) + ');\n'
    body = 'wire rn;\n' + cell('inv_1','reset_polarity',I='reset',ZN='rn')
    if model == 'ChiselAsyncClosingLatch_v1' and set(params) == {'WIDTH','DELAY_FS'}:
        body += 'wire enable;\n' + cell('inv_1','gate_polarity',I='closed',ZN='enable')
        for bit in range(width):
            body += cell('latrnq_1',f'bit_{bit}',E='enable',D=f'd[{bit}]',RN='rn',Q=f'q[{bit}]')
        note = 'Resettable positive latch with explicit reset/gate inverters; characterize closure, setup/hold and reset paths of the complete adapter.'
    elif (model == 'ChiselAsyncControlGate_v1' and set(params) == {'WIDTH','OP','DELAY_FS','RESET_VALUE'}
          and params['OP'] in (0,1,2) and params['RESET_VALUE'] == 0):
        # data_delay accounts for mapped logic; it is never replaced by a second
        # independently sized matched-delay chain.
        if any('data_delay' in p.split('.')[-1] for p in required['instances']):
            return None, 'Map the actual transform/glue path and its reset behavior; no automatic extra data-delay chain.'
        if params['OP'] == 0 and (stages is None or not 1 <= stages <= 4096):
            return None, 'Supply an explicit trial buffer count; fs model values cannot determine a physical chain length.'
        for bit in range(width):
            count = stages if params['OP'] == 0 else 0
            body += f'wire [{count}:0] chain_{bit};\n'
            value = f'a[{bit}]'
            if params['OP']:
                value = f'logic_{bit}'
                body += f'wire {value};\n'
                body += cell('inv_1',f'logic_cell_{bit}',I=f'a[{bit}]',ZN=value) if params['OP']==1 else cell(
                    'or2_1',f'logic_cell_{bit}',A1=f'a[{bit}]',A2=f'b[{bit}]',Z=value)
            body += cell('and2_1',f'reset_{bit}',A1=value,A2='rn',Z=f'chain_{bit}[0]')
            for i in range(count):
                body += cell('buf_1',f'delay_{bit}_{i}',I=f'chain_{bit}[{i}]',Z=f'chain_{bit}[{i+1}]')
            body += f'assign q[{bit}]=chain_{bit}[{count}];\n'
        note = ('Trial chain of '+str(stages)+' buffers' if params['OP']==0 else 'Combinational gate') + ' plus reset gating. No delay guarantee until characterized, constrained and extracted.'
    else:
        return None, 'Requires a reviewed technology implementation of this exact state/control/reset specialization.'
    return (header + body + 'endmodule\n', sorted(set(cells)), note), None


def prepare(required_file, liberty, output, stages=None):
    required = json.loads(required_file.read_text(encoding='utf-8'))
    if not required:
        raise ValueError('EMPTY_CELL_INVENTORY')
    lib = liberty.read_text(encoding='utf-8')
    output.mkdir(parents=True, exist_ok=False)
    result = dict(status='PARTIAL_REFERENCE', technology=PREFIX.rstrip('_'),
                  required_sha256=hashlib.sha256(required_file.read_bytes()).hexdigest(),
                  liberty_sha256=hashlib.sha256(liberty.read_bytes()).hexdigest(),
                  adapters=[], missing=[])
    sources = []
    for index, entry in enumerate(required):
        name = f'Gf180Trial_{index}'
        candidate, reason = adapter(entry, name, stages)
        if candidate:
            source, cells, note = candidate
            absent = [PREFIX+c for c in cells if not re.search(r'\bcell\s*\(\s*"?'+re.escape(PREFIX+c)+r'"?\s*\)',lib)]
            if absent:
                reason = 'LIBERTY_CELL_MISSING: ' + ', '.join(absent)
            else:
                sources.append(source)
                result['adapters'].append(dict(cell=entry['cell'],module=name,
                    pins={p['name']:p['name'] for p in entry['ports']}, instances=entry['instances'],
                    provenance=note, cells=cells))
        if reason:
            result['missing'].append(dict(cell=entry['cell'],instances=entry['instances'],reason=reason))
    text = '// Experimental topology only. Characterization and physical checks required.\n' + '\n'.join(sources)
    (output/'adapters.v').write_text(text,encoding='utf-8')
    result['adapters_sha256'] = hashlib.sha256((output/'adapters.v').read_bytes()).hexdigest()
    if not result['missing']:
        result['status'] = 'TOPOLOGIES_ONLY_UNQUALIFIED'
    (output/'reference.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--required',type=Path,required=True)
    parser.add_argument('--liberty',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--trial-buffer-count',type=int)
    args=parser.parse_args()
    result=prepare(args.required,args.liberty,args.output,args.trial_buffer_count)
    print(f"{result['status']}: {len(result['adapters'])} adapters; {len(result['missing'])} missing specializations")
    raise SystemExit(2 if result['missing'] else 0)
