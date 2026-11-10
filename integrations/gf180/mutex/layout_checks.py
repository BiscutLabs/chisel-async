# SPDX-License-Identifier: Apache-2.0
"""Checks for experimental layout evidence; never grants physical qualification."""
from collections import Counter
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def drc_report(path):
    root = ET.parse(path).getroot()
    categories = {n.findtext('name') for n in root.findall('./categories/category')}
    if root.find('./items') is None or root.tag != 'report-database' or not {'NP.1', 'DF.1a_LV', 'M1.1'} <= categories:
        raise ValueError('MUTEX_DRC_INCOMPLETE_REPORT')
    failures = Counter(n.findtext('category') for n in root.findall('./items/item'))
    if failures:
        raise ValueError('MUTEX_DRC_VIOLATIONS:' + str(dict(failures)))
    return {'rules_reported': len(categories), 'violations': 0}


def lvs_log(path, kind):
    text = Path(path).read_text()
    good = {'netgen': 'Final result: Circuits match uniquely.',
            'klayout': 'INFO : Congratulations! Netlists match.'}[kind]
    if good not in text or re.search(r"Netlists don't match|Circuits do not match|ERROR", text):
        raise ValueError('MUTEX_LVS_MISMATCH:' + kind)


def number(value):
    m = re.fullmatch(r'([+\-\d.eE]+)([fpnumk]?)', value.lower())
    if not m:
        raise ValueError('MUTEX_SPICE_NUMBER:' + value)
    n = float(m[1]) * {'': 1, 'f': 1e-15, 'p': 1e-12, 'n': 1e-9,
                       'u': 1e-6, 'm': 1e-3, 'k': 1e3}[m[2]]
    if not math.isfinite(n) or n < 0:
        raise ValueError('MUTEX_SPICE_NONPHYSICAL_VALUE')
    return n


def spice(path):
    ports = []; devices = []; resistors = []; capacitors = []
    logical = []
    for raw in Path(path).read_text().splitlines():
        line = raw.split('$ **')[0].strip()
        if not line or line.startswith('*'):
            continue
        if line.startswith('+'):
            logical[-1] += ' ' + line[1:]
        else:
            logical.append(line)
    for line in logical:
        row = line.lower().split()
        if row[0] == '.subckt':
            if ports:
                raise ValueError('MUTEX_SPICE_MULTIPLE_CIRCUITS')
            ports = row[2:]
        elif row[0] == '.ends':
            continue
        elif row[0].startswith(('x', 'm')):
            if row[5] not in ('nfet_03v3', 'pfet_03v3'):
                raise ValueError('MUTEX_SPICE_DEVICE')
            params = dict(x.split('=') for x in row[6:])
            if set(params) - {'w', 'l', 'ad', 'as', 'pd', 'ps'}:
                raise ValueError('MUTEX_SPICE_PARAMETERS')
            devices.append((row[5], row[1:5], {k: number(v) for k, v in params.items()}))
        elif row[0].startswith(('r', 'c')) and len(row) == 4:
            (resistors if row[0][0] == 'r' else capacitors).append((row[1], row[2], number(row[3])))
        else:
            raise ValueError('MUTEX_SPICE_UNSUPPORTED:' + line)
    if not ports or not devices:
        raise ValueError('MUTEX_SPICE_EMPTY')
    return ports, devices, resistors, capacitors


def rc_connectivity(lvs_spice, rc_spice):
    """Short extracted resistors and compare all device pins/geometry to LVS view.

    This requires preserved internal labels; arbitrary net renaming is handled by
    LVS, not guessed here. Reject accidental removal/merging of individual FETs.
    """
    ports, baseline, _, _ = spice(lvs_spice)
    rc_ports, devices, resistors, capacitors = spice(rc_spice)
    if rc_ports != ports or not resistors or not capacitors:
        raise ValueError('MUTEX_RC_MISSING_OR_PORTS')
    parent = {}
    def find(n):
        parent.setdefault(n, n)
        if parent[n] != n:
            parent[n] = find(parent[n])
        return parent[n]
    for a, b, _ in resistors:
        parent[find(b)] = find(a)
    aliases = {}
    for _, nodes, _ in baseline:
        for n in nodes:
            root = find(n)
            if root in aliases and aliases[root] != n:
                raise ValueError('MUTEX_RC_SHORTED_NETS')
            aliases[root] = n
    for n in ports:
        if aliases.get(find(n)) != n:
            raise ValueError('MUTEX_RC_PORT_DISCONNECTED')
    def key(device, extracted):
        kind, nodes, params = device
        if extracted:
            try:
                nodes = [aliases[find(n)] for n in nodes]
            except KeyError as error:
                raise ValueError('MUTEX_RC_DEVICE_DISCONNECTED') from error
        # Symmetric source/drain may permute; gate and body must match exactly.
        return (kind, tuple(sorted(((nodes[0], params.get('ad'), params.get('pd')),
                                   (nodes[2], params.get('as'), params.get('ps'))))),
                nodes[1], nodes[3], params['w'], params['l'])
    if Counter(key(d, False) for d in baseline) != Counter(key(d, True) for d in devices):
        raise ValueError('MUTEX_RC_DEVICE_MISMATCH')
    live = set(aliases)
    if any(find(n) not in live for a, b, _ in resistors + capacitors for n in (a, b)):
        raise ValueError('MUTEX_RC_FLOATING_NETWORK')
    return dict(devices=len(devices), resistors=len(resistors), capacitors=len(capacitors),
                nets=len(aliases), max_resistance_ohm=max(r[2] for r in resistors),
                max_capacitance_f=max(c[2] for c in capacitors))
