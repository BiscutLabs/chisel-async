# SPDX-License-Identifier: Apache-2.0
"""Independent event-order specification transcribed from Furber-Day Fig. 14.

Places are directed event dependencies, not Boolean controller equations.
The three initially marked places are the dots in the published STG.
"""
from collections import deque

EDGES = (
    ("Ain-", "Rin+"), ("Rin+", "A+"), ("B-", "A+"),
    ("A+", "Lt+"), ("A+", "Rout+"), ("Aout-", "Rout+"),
    ("Lt+", "Ain+"), ("Ain+", "Rin-"), ("Ain+", "B+"),
    ("Rin-", "Ain-"), ("B+", "Ain-"), ("B+", "A-"),
    ("Rout+", "Aout+"), ("Aout+", "A-"), ("A-", "Rout-"),
    ("Rout-", "Aout-"), ("Aout-", "Lt-"), ("Lt-", "B-"), ("Ain-", "B-"),
)
INITIAL = frozenset((("Ain-", "Rin+"), ("B-", "A+"), ("Aout-", "Rout+")))
EVENTS = tuple(sorted({event for edge in EDGES for event in edge}))


class LongHoldSTG:
    def __init__(self, edges=EDGES):
        self.edges = edges
        self.marking = set(INITIAL)
        self.levels = {event[:-1]: 0 for event in EVENTS}
        self.observations = 0

    def enabled(self, event):
        return all(edge in self.marking for edge in self.edges if edge[1] == event)

    def fire(self, event):
        assert event in EVENTS and self.enabled(event), f"STG_ORDER:{event}"
        signal, level = event[:-1], int(event[-1] == "+")
        assert self.levels[signal] != level, f"STG_ALTERNATION:{event}"
        incoming = {edge for edge in self.edges if edge[1] == event}
        outgoing = {edge for edge in self.edges if edge[0] == event}
        self.marking.difference_update(incoming)
        assert not outgoing.intersection(self.marking), "STG_UNSAFE_MARKING"
        self.marking.update(outgoing)
        self.levels[signal] = level
        self.observations += 1
        if event == "Lt-":
            assert self.levels["Aout"] == 0, "STG_EARLY_RELEASE"


def explore():
    """All reachable markings; check binary signal consistency and output persistence."""
    initial = LongHoldSTG()
    frontier = deque([initial])
    visited = {frozenset(initial.marking): initial.levels.copy()}
    transitions = 0
    while frontier:
        state = frontier.popleft()
        enabled = {event for event in EVENTS if state.enabled(event)}
        assert enabled, "STG_DEAD_MARKING"
        for event in enabled:
            successor = LongHoldSTG()
            successor.marking = state.marking.copy()
            successor.levels = state.levels.copy()
            successor.fire(event)
            assert all(successor.enabled(other) for other in enabled - {event}), "STG_NONPERSISTENT"
            transitions += 1
            key = frozenset(successor.marking)
            if key in visited:
                assert visited[key] == successor.levels, "STG_AMBIGUOUS_LEVELS"
            else:
                visited[key] = successor.levels.copy()
                frontier.append(successor)
    return {"markings": len(visited), "transitions": transitions}


def verify_trace(log, depth):
    import re
    models = [LongHoldSTG() for _ in range(depth)]
    observations = 0
    for line in log.splitlines():
        if line.startswith("EVENT ") and "reset=1" in line:
            observations += sum(model.observations for model in models)
            models = [LongHoldSTG() for _ in range(depth)]
        match = re.fullmatch(r"STG stage=(\d+) event=([A-Za-z]+[+-])", line)
        if match:
            models[int(match[1])].fire(match[2])
    observations += sum(model.observations for model in models)
    assert observations >= 40*14*depth, "STG_MISSING_ACTIVITY"
    assert all(model.marking == INITIAL for model in models), "STG_INCOMPLETE"
    return observations
