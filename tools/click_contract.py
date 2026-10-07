# SPDX-License-Identifier: Apache-2.0
"""Strict native Click contract validation and primitive wiring assertions."""
import re

ROLES = ('input_compare', 'output_compare', 'fire', 'input_phase', 'output_phase', 'payload', 'data_delay')
TIMES = ('REQUEST_FS', 'ACKNOWLEDGE_FS', 'OUTPUT_FS', 'SETUP_FS', 'HOLD_FS', 'PULSE_HIGH_FS', 'PULSE_LOW_FS', 'CLOCK_SKEW_FS')
REFS = ('in_request', 'in_data', 'in_acknowledge', 'out_request', 'out_data', 'out_acknowledge', 'capture', 'register_data')


def require(ok, code):
    if not ok:
        raise ValueError(code)


def marker_parameters(t, endpoints):
    return {'WIDTH': str(sum(endpoints[r]['width'] for r in t['endpoints'])),
            'DECOUPLED': str(int(t['variant'] == 'phase-decoupled')), 'SEEDED': str(int(t['initial_token'])),
            **t['times'], **{f'{r.upper()}_{b.upper()}_FS': t['cells'][r][b + '_fs']
                            for r in ROLES for b in ('min', 'max', 'model')}}


def validate(t, node, endpoints):
    require(set(t) == set('id kind marker variant initial_token endpoints times cells assumptions'.split()), 'CLICK_FIELDS')
    require(t['variant'] in ('standard', 'phase-decoupled') and type(t['initial_token']) is bool, 'CLICK_VARIANT')
    pd = t['variant'] == 'phase-decoupled'
    seeded = t['initial_token']
    require(not seeded or pd, 'CLICK_INITIALIZATION')
    require(t['endpoints'] == list(REFS) + (['start'] if seeded else []), 'CLICK_ENDPOINTS')
    require(set(t['times']) == set(TIMES) and set(t['cells']) == set(ROLES), 'CLICK_TIMING_INVENTORY')
    for b in t['cells'].values():
        require(set(b) == {'min_fs','max_fs','model_fs'}, 'CLICK_BOUND_FIELDS')
    for value in [*t['times'].values(), *(v for b in t['cells'].values() for v in b.values())]:
        require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]*', value) and int(value) <= 2**63-1, 'INVALID_MODEL_TIME')
    c = {r: {k: int(v) for k,v in b.items()} for r,b in t['cells'].items()}
    s = {k:int(v) for k,v in t['times'].items()}
    require(all(0 <= b['min_fs'] <= b['model_fs'] <= b['max_fs'] for b in c.values()), 'INVALID_DELAY_BOUNDS')
    require(all(b['min_fs'] > 0 for r,b in c.items() if r != 'data_delay'), 'CLICK_POSITIVE_CELL_BOUNDS')
    require(s['PULSE_HIGH_FS'] > 0 and s['PULSE_LOW_FS'] > 0, 'CLICK_POSITIVE_PULSE_REQUIREMENTS')
    require(s['REQUEST_FS'] > c['data_delay']['max_fs'] + s['SETUP_FS'], 'CLICK_DATA_GUARD')
    shortest = min(c['input_phase']['min_fs'], c['output_phase']['min_fs']) + min(
        c['input_compare']['min_fs'], c['output_compare']['min_fs']) + c['fire']['min_fs']
    require(shortest > s['PULSE_HIGH_FS'] + s['CLOCK_SKEW_FS'], 'CLICK_HIGH_PULSE_BOUND')
    settled = s['CLOCK_SKEW_FS'] + max(c['input_phase']['max_fs'],c['output_phase']['max_fs']) + max(
        c['input_compare']['max_fs'],c['output_compare']['max_fs']) + c['fire']['max_fs']
    require(s['ACKNOWLEDGE_FS'] > max(settled+s['PULSE_LOW_FS'],s['CLOCK_SKEW_FS']+s['HOLD_FS']), 'CLICK_ACK_GUARD')
    require(s['OUTPUT_FS'] > max(settled+s['PULSE_LOW_FS'],s['CLOCK_SKEW_FS']+c['payload']['max_fs']), 'CLICK_OUTPUT_GUARD')
    channels = {ch['id']: ch for ch in node['channels']}
    require(set(channels) == {'in','out'} and all(ch['protocol']=='two-phase-bundled-v1' for ch in channels.values())
            and channels['in']['role']=='input' and channels['out']['role']=='output', 'CLICK_CHANNELS')
    require(node['capacity']==1 and not node['children'], 'CLICK_CAPACITY')
    cells = {p['id']:p for p in node['primitives'] if p['view']=='behavioral'}
    expected = set(ROLES) - (set() if pd else {'output_phase'}) | {'request_delay','acknowledge_guard','output_guard'}
    if seeded:
        expected.add('start_barrier')
    require(set(cells)==expected, 'CLICK_CELL_INVENTORY')
    for name,p in cells.items():
        params=p['parameters']
        delay = (t['times'][{'request_delay':'REQUEST_FS','acknowledge_guard':'ACKNOWLEDGE_FS','output_guard':'OUTPUT_FS'}[name]]
                 if name.endswith('_guard') or name=='request_delay' else t['cells']['fire' if name=='start_barrier' else name]['model_fs'])
        base={'DELAY_FS': delay}
        if name.endswith('_compare'):
            model='ChiselAsyncXor_v1'
        elif name.endswith('_phase'):
            model='ChiselAsyncPhaseRegister_v1'; base['RESET_VALUE']=str(int(name=='output_phase' and seeded))
        elif name in ('fire','start_barrier'):
            model='ChiselAsyncAnd_v1'; base.update(INPUTS='2',INVERT='2' if name=='fire' else '0')
        elif name=='payload':
            model='ChiselAsyncEventRegister_v1'
            width=endpoints['out_data']['width']
            value=params.get('RESET_VALUE','-1')
            require(re.fullmatch(r'0|[1-9][0-9]*',value) and int(value)<2**width and (seeded or value=='0'), 'CLICK_INITIAL_PAYLOAD')
            base.update(WIDTH=str(width),RESET_VALUE=value)
        else:
            model='ChiselAsyncControlGate_v1'
            base.update(WIDTH=str(endpoints['out_data']['width'] if name=='data_delay' else 1), OP='0',
                        RESET_VALUE=str(int(name=='output_guard' and seeded)))
        require(p['model']==model and params==base, 'CLICK_CELL_PARAMETERS')


def bindings(t, node, endpoints):
    """Pairs checked with independently forced primitive outputs by the resolver."""
    c={p['id']:p['rtl_path'] for p in node['primitives']}
    e={k:v['rtl_path'] for k,v in endpoints.items()}
    phase=c['output_phase'] if t['variant']=='phase-decoupled' else c['input_phase']
    pairs=[(c['request_delay']+'.a',e['in_request']),
           (c['input_compare']+'.a',c['request_delay']+'.q'),
           (c['input_compare']+'.b',c['input_phase']+'.q'),
           (c['output_compare']+'.a',phase+'.q'),(c['output_compare']+'.b',e['out_acknowledge']),
           (c['fire']+'.d',"{"+c['output_compare']+'.q,'+c['input_compare']+'.q}'),
           (e['capture'],c['fire']+'.q'),(c['input_phase']+'.trigger',e['capture']),
           (c['payload']+'.trigger',e['capture']), (c['payload']+'.d',c['data_delay']+'.q'),
           (e['register_data'],c['payload']+'.d'),(e['out_data'],c['payload']+'.q'),
           (c['acknowledge_guard']+'.a',c['input_phase']+'.q'),(e['in_acknowledge'],c['acknowledge_guard']+'.q'),
           (c['output_guard']+'.a',phase+'.q')]
    if t['variant']=='phase-decoupled':
        pairs.append((c['output_phase']+'.trigger',e['capture']))
    if t['initial_token']:
        pairs += [(c['start_barrier']+'.d',"{"+e['start']+','+c['output_guard']+'.q}'),
                  (e['out_request'],c['start_barrier']+'.q')]
    else:
        pairs.append((e['out_request'],c['output_guard']+'.q'))
    return pairs
