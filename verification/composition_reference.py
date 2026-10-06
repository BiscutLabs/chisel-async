# SPDX-License-Identifier: Apache-2.0
"""External token obligations only: no cell equations or production state names."""
from collections import deque
from reference import FourPhaseContract


INITIAL = [0x12, 0x12, 0xe7]
WIDE_INITIAL = [1 << 64, (1 << 65)-1, 1 << 32, 1 << 32]


class CompositionLedger:
    def __init__(self, fixture, ports):
        self.fixture, self.ports = fixture, ports
        self.protocol = {p: FourPhaseContract() for p in ports}
        self.accepted = self.delivered = self.returned = self.aborted = self.resets = 0
        self.initialized = self.peak = 0
        self.by_port = {p: 0 for p in ports}
        self.queue, self.left, self.right = deque(), deque(), deque()
        self.offers = {}
        self.fork_deliveries, self.fork_returns = set(), set()
        self.reserved = 0
        self.feedback_next = 7
        self.fork_offered = 0
        self.fork_aborted = {p: 0 for p, role in ports.items() if role == 'output'}

    def reset(self):
        if self.fixture=='fork' and 'in' in self.offers:
            for p in self.fork_aborted:
                if p not in self.fork_deliveries: self.fork_aborted[p] += 1
        self.aborted += len(self.queue) + len(self.left) + len(self.right)
        self.queue.clear(); self.left.clear(); self.right.clear()
        self.offers.clear(); self.fork_deliveries.clear(); self.fork_returns.clear()
        self.reserved = 0
        self.feedback_next = 7
        for p in self.protocol.values(): p.reset()
        if self.fixture in ('initialized_fifo', 'initial_tokens', 'initial_wide'):
            initial = WIDE_INITIAL if self.fixture=='initial_wide' else INITIAL
            self.queue.extend(initial)
            self.reserved = len(initial)
            self.initialized += len(initial)
            self.peak = max(self.peak, self.reserved)
        self.resets += 1

    def expected(self, port):
        f = self.fixture
        if f == 'fork':
            assert 'in' in self.offers, 'FORK_UNEXPECTED'
            return self.offers['in']
        if f == 'feedback': return self.feedback_next
        if f == 'join':
            assert self.left and self.right, 'JOIN_MISSING_OPERAND'
            return (self.left[0], self.right[0])
        assert self.queue, 'UNEXPECTED_TOKEN'
        value = self.queue[0]
        if f == 'select':
            assert port == f'out_{value[0]}', 'SELECT_ROUTE'
            return value[1]
        if f == 'fork_join': return (value ^ 0xa5, value + 1)
        return value

    def edge(self, port, signal, value, payload):
        self.protocol[port].edge(signal, value)
        f = self.fixture
        incoming = self.ports[port] == 'input'
        if signal == 'req' and value:
            self.offers[port] = payload
            if incoming and f=='fork': self.fork_offered += 1
            if not incoming:
                diagnostic = 'JOIN_PAIR' if f in ('join', 'fork_join') else 'PAYLOAD_MISMATCH'
                assert payload == self.expected(port), diagnostic
        if signal == 'ack' and value:
            if incoming:
                if f == 'fork':
                    assert len(self.fork_deliveries) == 3, 'FORK_EARLY_ACCEPT'
                elif f == 'join':
                    q = self.left if port == 'left' else self.right
                    assert not q, 'JOIN_CAPACITY'
                    q.append(payload)
                else:
                    self.queue.append(payload)
                    self.reserved += 1
                    capacity = {'fifo_one': 1, 'fifo': 3, 'initialized_fifo': 3, 'select': 1, 'merge': 1}.get(f)
                    if capacity: assert self.reserved <= capacity, 'CAPACITY_EXCEEDED'
                    self.peak = max(self.peak, self.reserved)
                self.accepted += 1
            else:
                diagnostic = 'JOIN_PAIR' if f in ('join', 'fork_join') else 'PAYLOAD_MISMATCH'
                assert payload == self.expected(port), diagnostic
                if f == 'fork':
                    assert port not in self.fork_deliveries, 'FORK_DUPLICATE'
                    self.fork_deliveries.add(port)
                elif f == 'join': self.left.popleft(); self.right.popleft()
                elif f == 'feedback': self.feedback_next = (self.feedback_next + 1) & 255
                else: self.queue.popleft()
                self.delivered += 1
                self.by_port[port] += 1
        if signal == 'ack' and not value:
            if incoming and f == 'fork':
                assert len(self.fork_returns) == 3, 'FORK_EARLY_RETURN'
                self.fork_deliveries.clear(); self.fork_returns.clear()
            if not incoming:
                if f == 'fork': self.fork_returns.add(port)
                elif f not in ('join', 'feedback'): self.reserved -= 1
                self.returned += 1
            self.offers.pop(port, None)
        self.check()

    def check(self):
        f=self.fixture
        if f=='fork':
            for p in self.fork_aborted:
                pending=int('in' in self.offers and p not in self.fork_deliveries)
                assert self.fork_offered==self.by_port[p]+self.fork_aborted[p]+pending, 'FORK_CONSERVATION'
        elif f=='join':
            assert self.accepted==2*self.delivered+self.aborted+len(self.left)+len(self.right), 'JOIN_CONSERVATION'
        elif f!='feedback':
            assert self.accepted+self.initialized==self.delivered+self.aborted+len(self.queue), 'TOKEN_CONSERVATION'

    def summary(self):
        return {name: getattr(self, name) for name in
                ('accepted', 'delivered', 'returned', 'aborted', 'resets', 'initialized', 'peak', 'by_port',
                 'fork_offered', 'fork_aborted')}


def replay(fixture, ports, events):
    ledger = CompositionLedger(fixture, ports)
    held = {}
    last_time = -1
    for event in events:
        assert event['time_fs'] >= last_time, 'TRACE_ORDER'
        last_time = event['time_fs']
        if event['kind'] == 'reset':
            ledger.reset(); held.clear()
        elif event['kind'] == 'edge':
            p, s, v = event['port'], event['signal'], event['value']
            payload = tuple(event['payload']) if isinstance(event['payload'], list) else event['payload']
            if s == 'req' and v: held[p] = payload
            if s == 'ack' and not v: held.pop(p, None)
            ledger.edge(p, s, v, payload)
        elif event['kind'] == 'data':
            value = tuple(event['payload']) if isinstance(event['payload'], list) else event['payload']
            assert event['port'] not in held or held[event['port']] == value, 'COMPOSITION_DATA_HOLD'
        else: raise AssertionError('UNKNOWN_TRACE_EVENT')
    return ledger.summary()
