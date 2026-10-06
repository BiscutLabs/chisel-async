# SPDX-License-Identifier: Apache-2.0
"""Event-driven composition tests with passive port traces and a separate token ledger."""
import itertools
import json
import os
from pathlib import Path

import cocotb
from cocotb.triggers import Timer, with_timeout
from cocotb.utils import get_sim_time
from composition_reference import CompositionLedger, INITIAL

FIXTURE = os.environ['COMPOSITION_FIXTURE']
SCENARIO = os.environ.get('COMPOSITION_SCENARIO', 'normal')
SEED = int(os.environ.get('COMPOSITION_SEED', '0'))


async def tick(n=1): await Timer(n, unit='ns')


async def wait(signal, value):
    async def until():
        while int(signal.value) != value: await signal.value_change
    await with_timeout(until(), 20000, 'ns')


class Port:
    def __init__(self, dut, name, fields, incoming):
        self.name, self.incoming = name, incoming
        self.req, self.ack = getattr(dut, name+'_req'), getattr(dut, name+'_ack')
        self.fields = [getattr(dut, name+'_bits'+suffix) for suffix in fields]

    def read(self):
        parts = tuple(int(h.value) for h in self.fields)
        return parts[0] if len(parts) == 1 else parts

    def write(self, data):
        for h, part in zip(self.fields, data if isinstance(data, tuple) else (data,)): h.value = part

    async def send(self, data, pause=1, held=1):
        self.write(data); await tick(pause)
        self.req.value = 1; await wait(self.ack, 1)
        await tick(held); self.req.value = 0
        await wait(self.ack, 0); await tick(pause)

    async def receive(self, pause=1, returned=1):
        await wait(self.req, 1); await tick(pause)
        self.ack.value = 1; await wait(self.req, 0)
        await tick(returned); self.ack.value = 0; await tick(1)


def ports(dut):
    f = FIXTURE
    result = {}
    def add(name, incoming, fields=('',)):
        result[name] = Port(dut, name, fields, incoming)
    if f == 'join':
        add('left', True); add('right', True); add('out', False, ('_left', '_right'))
    elif f == 'merge':
        for i in range(3): add(f'in_{i}', True)
        add('out', False)
    elif f in ('fork','select'):
        add('in', True, ('_index','_data') if f == 'select' else ('',))
        for i in range(3): add(f'out_{i}', False)
    else:
        if f not in ('initial_tokens','initial_wide','feedback'): add('in', True)
        add('out', False, ('_left','_right') if f == 'fork_join' else ('',))
    return result


class Monitor:
    def __init__(self, dut, ps, directory):
        self.dut, self.ps = dut, ps
        self.ledger = CompositionLedger(FIXTURE, {p: 'input' if v.incoming else 'output' for p,v in ps.items()})
        self.stream = (directory/'trace.jsonl').open('w',encoding='utf-8')
        self.tasks, self.failure, self.held = [], None, {}
        self.events = 0

    def record(self, kind, **kw):
        self.events += 1
        self.stream.write(json.dumps(dict(time_fs=int(get_sim_time(unit='fs')),kind=kind,**kw))+'\n')
        self.stream.flush()

    def reset(self):
        self.record('reset'); self.ledger.reset(); self.held.clear()

    def check(self): assert self.failure is None, self.failure

    def start(self):
        for p in self.ps.values():
            for signal in ('req','ack'): self.tasks.append(cocotb.start_soon(self.control(p,signal)))
            for field in p.fields: self.tasks.append(cocotb.start_soon(self.data(p,field)))

    async def control(self,p,signal):
        h=getattr(p,signal)
        while True:
            await h.value_change
            if int(self.dut.reset.value): continue
            try:
                v=int(h.value); value=p.read()
                self.record('edge',port=p.name,signal=signal,value=v,payload=value)
                if signal=='req' and v: self.held[p.name]=value
                if signal=='ack' and not v: self.held.pop(p.name,None)
                self.ledger.edge(p.name,signal,v,value)
            except (AssertionError,ValueError) as e:
                if self.failure is None: self.failure=str(e).splitlines()[0]

    async def data(self,p,h):
        while True:
            await h.value_change
            if int(self.dut.reset.value): continue
            try:
                value=p.read(); self.record('data',port=p.name,payload=value)
                assert p.name not in self.held or value==self.held[p.name], 'COMPOSITION_DATA_HOLD'
            except (AssertionError,ValueError) as e:
                if self.failure is None: self.failure=str(e).splitlines()[0]


@cocotb.test()
async def composition_contract(dut):
    directory=Path(os.environ['COMPOSITION_OUTPUT'])
    ps=ports(dut); m=Monitor(dut,ps,directory); tasks=[]
    # LCG traffic is local to this driver; expectation code does not import it.
    rng=SEED+1
    def pause():
        nonlocal rng
        rng=(1664525*rng+1013904223)&0xffffffff
        return 1+rng%53
    async def reset():
        dut.reset.value=1; await tick()
        for p in ps.values():
            if p.incoming: p.req.value=0; p.write(tuple(0 for _ in p.fields) if len(p.fields)>1 else 0)
            else: p.ack.value=0
        m.reset(); await tick(1000); dut.reset.value=0; await tick(1)
    def launch(coro):
        t=cocotb.start_soon(coro); tasks.append(t); return t
    async def finish(ts):
        for t in ts: await with_timeout(t, 200000, 'ns')
        await tick(100); m.check()
    async def sends(p, data):
        for i,x in enumerate(data): await p.send(x,pause(),500 if i%17==0 else pause())
    async def receives(p,n):
        for _ in range(n): await p.receive(pause(),pause())
    async def stream(count):
        data=([0,255,0x55,0x55]+[1<<i for i in range(8)]+[255^(1<<i) for i in range(8)]
              +[(i*37+SEED)&255 for i in range(count)])[:count]
        f=FIXTURE
        if f=='fork':
            await finish([launch(sends(ps['in'],data))]+[launch(receives(ps[f'out_{i}'],count)) for i in range(3)])
        elif f=='select':
            values=[(i%3,x) for i,x in enumerate(data)]
            await finish([launch(sends(ps['in'],values))]+
                         [launch(receives(ps[f'out_{i}'],sum(v[0]==i for v in values))) for i in range(3)])
        elif f=='merge':
            async def merged():
                for i,x in enumerate(data): await ps[f'in_{i%3}'].send(x,pause(),pause())
            await finish([launch(merged()),launch(receives(ps['out'],count))])
        elif f=='join':
            await finish([launch(sends(ps['left'],data)),launch(sends(ps['right'],[(x*3+257)&511 for x in data])),
                          launch(receives(ps['out'],count))])
        elif f in ('initial_tokens','initial_wide','feedback'):
            await finish([launch(receives(ps['out'],3 if f=='initial_tokens' else 4 if f=='initial_wide' else count))])
            if f!='feedback': assert int(dut.done.value)==1, 'INITIAL_SEQUENCE_NOT_COMPLETE'
        else:
            extra=3 if f=='initialized_fifo' else 0
            await finish([launch(sends(ps['in'],data)),launch(receives(ps['out'],count+extra))])
    try:
        dut.reset.value=1
        for p in ps.values():
            if p.incoming: p.req.value=0; p.write(tuple(0 for _ in p.fields) if len(p.fields)>1 else 0)
            else: p.ack.value=0
        await tick(1000); m.start(); await reset()
        if SCENARIO.startswith('merge_contention'):
            ps['in_0'].write(17); ps['in_1'].write(34); await tick(1)
            ps['in_0'].req.value=1
            if SCENARIO=='merge_contention_return':
                await wait(ps['in_0'].ack,1); await tick(1); ps['in_0'].req.value=0
            ps['in_1'].req.value=1
            await tick(1000)
            raise AssertionError('MISSING_EXCLUSIVITY_DIAGNOSTIC')
        if SCENARIO=='invalid_select':
            ps['in'].write((3,17)); await tick(1); ps['in'].req.value=1
            await tick(1000); raise AssertionError('MISSING_SELECT_DIAGNOSTIC')

        if FIXTURE in ('fifo_one','fifo','initialized_fifo'):
            depth=1 if FIXTURE=='fifo_one' else 3
            fill=depth-(3 if FIXTURE=='initialized_fifo' else 0)
            for i in range(fill): await ps['in'].send(80+i)
            pending=launch(ps['in'].send(0x99)); await tick(2000); m.check()
            assert not int(ps['in'].ack.value), 'FIFO_OVER_ACCEPT'
            assert m.ledger.reserved==depth, 'FIFO_MISSING_CAPACITY'
            await finish([pending,launch(receives(ps['out'],depth+1))])
            await reset()
            # Reset a saturated pipeline with an unaccepted external offer.
            for i in range(fill): await ps['in'].send(90+i)
            pending=launch(ps['in'].send(0xee)); await tick(2000); m.check()
            assert not int(ps['in'].ack.value) and m.ledger.reserved==depth, 'FIFO_RESET_CAPACITY'
            before=m.ledger.aborted
            pending.cancel()
            await reset()
            assert m.ledger.aborted-before==depth, 'FIFO_RESET_ACCOUNTING'
        if FIXTURE=='fork':
            # All 6 acceptance orders x all 6 return orders, including long holds.
            for accept in itertools.permutations(range(3)):
                for returned in itertools.permutations(range(3)):
                    ps['in'].write(0x5a); await tick(1); ps['in'].req.value=1
                    for i in accept:
                        await wait(ps[f'out_{i}'].req,1); await tick(20)
                        ps[f'out_{i}'].ack.value=1; await tick(20); m.check()
                    await wait(ps['in'].ack,1); await tick(500); ps['in'].req.value=0
                    for i in returned:
                        await wait(ps[f'out_{i}'].req,0); await tick(20)
                        ps[f'out_{i}'].ack.value=0; await tick(20); m.check()
                    await wait(ps['in'].ack,0); await tick(1)
        if FIXTURE=='select':
            await ps['in'].send((1,0x55))
            await wait(ps['out_1'].req,1)
            # The input handshake is complete; subsequent input changes are legal.
            ps['in'].write((2,0xaa)); await tick(500); m.check()
            assert not int(ps['out_0'].req.value) and not int(ps['out_2'].req.value), 'SELECT_ROUTE'
            await ps['out_1'].receive(); await tick(100); m.check()
        if FIXTURE=='join':
            await ps['left'].send(80)
            pending=launch(ps['left'].send(81)); await tick(500); m.check()
            assert not int(ps['left'].ack.value) and not int(ps['out'].req.value), 'JOIN_CAPACITY'
            await finish([pending,launch(sends(ps['right'],[300,301])),launch(receives(ps['out'],2))])
        await stream(64)

        # Reset at output offer, acknowledged, and return phases. Fork resets after
        # partial branch delivery; join resets with only one stored operand as well.
        for phase in range(3):
            await reset()
            new=[]
            if FIXTURE=='join':
                new.append(launch(ps['left'].send(0x63)))
                if phase>0: new.append(launch(ps['right'].send(0x143)))
            elif FIXTURE=='merge': new.append(launch(ps['in_1'].send(0x63)))
            elif FIXTURE not in ('initial_tokens','initial_wide','feedback'):
                new.append(launch(ps['in'].send((1,0x63) if FIXTURE=='select' else 0x63)))
            output=ps['out_1'] if FIXTURE=='select' else ps['out_0'] if FIXTURE=='fork' else ps['out']
            if FIXTURE=='join' and phase==0:
                await wait(ps['left'].ack,1); await tick(500)
                assert not int(output.req.value), 'JOIN_EARLY_OUTPUT'
            else:
                await wait(output.req,1); await tick(500)
                if phase>0:
                    output.ack.value=1; await tick(1)
                    if phase==2 and FIXTURE!='fork': await wait(output.req,0)
                await tick(20)
            m.check()
            for t in new: t.cancel()
            await reset(); await stream(8)
        m.check()
        expected = {'fifo_one':92, 'fifo':94, 'initialized_fifo':106, 'initial_tokens':14,
                    'fork':374,'join':92,'select':91,'initial_wide':18}.get(FIXTURE,90)
        assert m.ledger.delivered==expected, 'MISSING_COMPOSITION_ACTIVITY'
        result=dict(status='PASS',**m.ledger.summary(),events=m.events)
    except BaseException as error:
        result=dict(status='FAIL',diagnostic=m.failure or str(error).splitlines()[0],**m.ledger.summary(),events=m.events)
        raise AssertionError(result['diagnostic']) from error
    finally:
        for t in tasks+m.tasks: t.cancel()
        m.stream.close()
        if 'result' in locals(): (directory/'evidence.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
