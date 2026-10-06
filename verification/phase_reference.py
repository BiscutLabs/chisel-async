# SPDX-License-Identifier: Apache-2.0
"""External protocol/obligation oracle. No controller state, gate equations or delays.

Input offers create obligations; completion is counted separately because a sequential
converter or fork may deliver downstream before completing its upstream handshake.
Reset cancels only undelivered obligations, never a previously delivered output.
"""
from collections import Counter, deque


class Protocol:
    def __init__(self, encoding, width):
        self.encoding, self.width = encoding, width
        self.reset()
        self.completion_polarities = Counter()

    def reset(self):
        self.req = self.ack = self.data = self.zero = 0
        self.rail_phase = 0
        self.held = None

    def observe(self, req, ack, data, zero=0):
        events = []
        if self.encoding == 'dual-rail-rtz-v1':
            mask = (1 << self.width)-1
            assert not zero & data, 'INVALID_RAIL'
            present, previous = zero | data, self.zero | self.data
            if self.rail_phase == 0:
                assert not ack, 'RAIL_EARLY_ACK'
                assert (self.zero & ~zero) == (self.data & ~data) == 0, 'RAIL_ORDER'
                if present == mask:
                    self.held = data; self.rail_phase = 1; events.append(('offer', data))
            elif self.rail_phase == 1:
                assert (data, zero) == (self.data, self.zero), 'RAIL_HOLD'
                if ack:
                    events.append(('complete', self.held)); self.rail_phase = 2
            elif self.rail_phase == 2:
                assert (data & ~self.data) == (zero & ~self.zero) == 0, 'RAIL_ORDER'
                assert ack or present == 0, 'RAIL_EARLY_SPACER'
                if not present:
                    self.rail_phase = 3 if ack else 0
                    if not ack: events.append(('return', self.held)); self.held = None
            else:
                assert not present, 'RAIL_ORDER'
                if not ack:
                    events.append(('return', self.held)); self.held = None; self.rail_phase = 0
        else:
            before, after = (self.req, self.ack), (req, ack)
            if self.encoding == 'four-phase-bundled-v1':
                if before != (0, 0) and after != (0, 0): assert data == self.held, 'DATA_HOLD'
                if before != after:
                    sequence = {(0,0):(1,0), (1,0):(1,1), (1,1):(0,1), (0,1):(0,0)}
                    assert sequence[before] == after, 'FOUR_PHASE_ORDER'
                    if after == (1,0): self.held = data; events.append(('offer', data))
                    elif after == (1,1): events.append(('complete', self.held))
                    elif after == (0,0): events.append(('return', self.held)); self.held = None
            else:
                assert self.encoding == 'two-phase-bundled-v1', 'UNKNOWN_ENCODING'
                if self.req != self.ack: assert data == self.held, 'DATA_HOLD'
                if before != after:
                    assert (req != self.req) != (ack != self.ack), 'TWO_PHASE_ORDER'
                    if req != self.req:
                        assert self.req == self.ack and req != ack, 'TWO_PHASE_ORDER'
                        self.held = data; events.append(('offer', data))
                    else:
                        assert self.req != self.ack and req == ack, 'TWO_PHASE_ORDER'
                        events += [('complete', self.held), ('return', self.held)]
                        self.held = None
        for event, _ in events:
            if event == 'complete': self.completion_polarities[ack] += 1
        self.req, self.ack, self.data, self.zero = req, ack, data, zero
        return events

    def idle(self):
        if self.encoding == 'two-phase-bundled-v1': return self.req == self.ack
        if self.encoding == 'dual-rail-rtz-v1': return self.rail_phase == 0 and self.data == self.zero == self.ack == 0
        return self.req == self.ack == 0


class Ledger:
    def __init__(self, fixture, channels):
        self.fixture, self.channels = fixture, channels
        self.monitors = {c['id']: Protocol(c['protocol'], sum(f['width'] for f in c['layout'])) for c in channels}
        self.inputs = {c['id'] for c in channels if c['role'] == 'input'}
        self.outputs = {c['id'] for c in channels if c['role'] == 'output'}
        self.stats = {k: Counter() for k in ('offers', 'completions', 'deliveries', 'aborted')}
        self.epochs = 0
        self.in_reset = True
        self.pending = {}
        self.queues = {}
        self.initial = [0x12, 0x12, 0xe7] if fixture in ('two_initial','two_initialized') else []
        self.join = fixture == 'two_join'
        self.merge = fixture in ('two_merge','arbiter','two_arbiter')

    def begin(self):
        self.epochs += 1
        self.queues = {name: deque() for name in (self.inputs if self.join or self.merge else self.outputs)}
        if self.initial: self.queues['out'].extend(self.initial)
        self.pending = {}

    def input_offer(self, name, data):
        if self.join or self.merge: self.queues[name].append(data)
        elif self.fixture == 'two_fork':
            for queue in self.queues.values(): queue.append(data)
        elif self.fixture == 'two_select':
            layout = next(c['layout'] for c in self.channels if c['id'] == name)
            fields = {f['field']: (data >> f['lsb']) & ((1<<f['width'])-1) for f in layout}
            assert fields['bits.index'] < 3, 'SELECT_INDEX'
            self.queues[f"out{fields['bits.index']}"].append(fields['bits.data'])
        else:
            self.queues['out'].append(data+1 if self.fixture == 'two_transform' else data)

    def output_offer(self, name, data):
        assert name not in self.pending, 'DUPLICATE_OFFER'
        if self.join:
            assert all(self.queues.values()), 'UNEXPECTED_TOKEN'
            layout = next(c['layout'] for c in self.channels if c['id'] == name)
            expected = sum(self.queues[f['field'].split('.')[1]][0] << f['lsb'] for f in layout)
            assert data == expected, 'JOIN_PAYLOAD'
            self.pending[name] = tuple(sorted(self.inputs))
        elif self.merge:
            candidates = [key for key,q in self.queues.items() if q and q[0] == data]
            assert candidates, 'ARBITRATION_PAYLOAD'
            # Traffic tags input lanes; no expected global winner/order is prescribed.
            assert len(candidates) == 1, 'AMBIGUOUS_TEST_PAYLOAD'
            self.pending[name] = tuple(candidates)
        else:
            assert self.queues[name], 'UNEXPECTED_TOKEN'
            assert self.queues[name][0] == data, 'PAYLOAD_MISMATCH'
            self.pending[name] = (name,)

    def observe(self, reset, name, req, ack, data, zero):
        if reset:
            if not self.in_reset:
                for key,q in self.queues.items(): self.stats['aborted'][key] += len(q)
            self.in_reset = True
            for monitor in self.monitors.values(): monitor.reset()
            return
        if self.in_reset:
            self.in_reset = False; self.begin()
        for event, value in self.monitors[name].observe(req, ack, data, zero):
            if name not in self.inputs and name not in self.outputs: continue
            if event == 'offer':
                self.stats['offers'][name] += 1
                if name in self.inputs: self.input_offer(name, value)
                else: self.output_offer(name, value)
            elif event == 'complete':
                self.stats['completions'][name] += 1
                if name in self.outputs:
                    assert name in self.pending, 'UNEXPECTED_COMPLETION'
                    for key in self.pending.pop(name): self.queues[key].popleft()
                    self.stats['deliveries'][name] += 1

    def finish(self):
        assert self.epochs == 3, 'RESET_ACTIVITY'
        assert not self.in_reset and all(m.idle() for m in self.monitors.values()), 'NOT_IDLE'
        assert not self.pending and not any(self.queues.values()), 'TOKEN_CONSERVATION'
        assert sum(self.stats['aborted'].values()) > 0, 'RESET_NOT_ACTIVATED'
        for c in self.channels:
            if c['protocol'] == 'two-phase-bundled-v1':
                assert all(self.monitors[c['id']].completion_polarities[p] > 0 for p in (0,1)), 'MISSING_COMPLETION_POLARITY'
        return {**{k:dict(v) for k,v in self.stats.items()}, 'epochs':self.epochs,
                'delivered':sum(self.stats['deliveries'].values()),
                'polarities':{k:dict(v.completion_polarities) for k,v in self.monitors.items()}}


def replay(fixture, channels, path, complete=True):
    ledger = Ledger(fixture, channels)
    last = -1
    for line in path.read_text(encoding='utf-8').splitlines():
        timestamp, reset, name, req, ack, data, zero = line.split('|')
        timestamp = int(timestamp)
        assert timestamp >= last, 'TRACE_TIME_ORDER'
        last = timestamp
        if reset == '1': ledger.observe(True, name, 0, 0, 0, 0)
        else:
            assert all(set(value.lower()) <= set('0123456789abcdef') for value in (req,ack,data,zero)), 'DIGITAL_UNKNOWN'
            try: ledger.observe(False, name, int(req,2), int(ack,2), int(data,16), int(zero,16))
            except AssertionError as error:
                error.add_note(f'{name} at {timestamp} fs: {line}')
                raise
    return ledger.finish() if complete else ledger
