# SPDX-License-Identifier: Apache-2.0
"""Portable properties for the optional GF180 layout flow (no PDK required)."""
import json
from pathlib import Path
import tempfile
import unittest

from layout import flatten, generate, HERE, placement, route
from layout_checks import drc_report, lvs_log, rc_connectivity
from layout_samples import analyze, deck, inventory


class LayoutTests(unittest.TestCase):
    def test_every_transistor_placed_with_separate_body(self):
        devices, ports = flatten((HERE/'mutex.spice').read_text())
        placed = placement(devices)
        self.assertEqual({d['name'] for d in placed}, {d['name'] for d in devices})
        self.assertEqual(len(placed), len(devices))
        for d in placed:
            self.assertEqual(d['nodes'][3], 'VDD' if d['kind'].startswith('p') else 'VSS')
            self.assertGreater(d['w'], 0)
            self.assertGreater(d['l'], 0)
        self.assertEqual(set(ports), {'RESET','R0','R1','G0','G1','VDD','VSS'})

    def test_route_connectivity_and_exclusion(self):
        pins = {'a':{(1,1,0),(4,4,0)},'b':{(1,4,0),(4,1,0)}}
        paths = route(pins, ['a','b'])
        seen = set()
        for net, edges in paths.items():
            nodes = {n for e in edges for n in e}
            self.assertTrue(pins[net] <= nodes)
            self.assertFalse(seen & nodes)
            connected = {next(iter(nodes))}
            while True:
                added = {n for e in edges if set(e)&connected for n in e} - connected
                if not added: break
                connected |= added
            self.assertEqual(nodes, connected)
            seen |= nodes
        with self.assertRaisesRegex(ValueError,'PIN_CONFLICT'):
            route({'a':{(1,1,0)},'b':{(1,1,0)}},['a','b'])

    def test_generation_has_all_critical_routes_and_bounded_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'cell'
            generate(p, Path(tmp)/'pdk')
            paths = json.loads((p/'routes.json').read_text())
            for name in ('X_N0','X_N1','X_F0','X_F1'):
                self.assertIn(name, paths)
                self.assertTrue(paths[name])
            geometry = json.loads((p/'geometry.json').read_text())
            self.assertLessEqual(geometry['area_mm2'],.001)
            self.assertEqual(geometry['status'],'unqualified')
            text = (p/'layout.tcl').read_text()
            self.assertIn('label X_N0 center',text)
            self.assertNotIn('/mnt/', text)
            self.assertNotIn('P:/', text)

    def test_reports_fail_on_mismatch_and_missing_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'report'
            p.write_text('<report-database><categories/></report-database>')
            with self.assertRaisesRegex(ValueError,'INCOMPLETE'):
                drc_report(p)
            base = '<report-database><categories>'+''.join('<category><name>'+n+'</name></category>' for n in ['NP.1','DF.1a_LV','M1.1'])+'</categories><items>{}</items></report-database>'
            p.write_text(base.format('<item><category>M1.1</category></item>'))
            with self.assertRaisesRegex(ValueError,'VIOLATIONS'):
                drc_report(p)
            for kind, message in [('netgen','Final result: Circuits match uniquely.'),('klayout','INFO : Congratulations! Netlists match.')]:
                p.write_text(message)
                lvs_log(p,kind)
                p.write_text(message+'\nERROR : Netlists don\'t match')
                with self.assertRaisesRegex(ValueError,'MISMATCH'):
                    lvs_log(p,kind)

    def test_rc_keeps_gate_body_and_every_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,q = (Path(tmp)/n for n in ('lvs.spice','rc.spice'))
            original = '.subckt c a b vss\nX0 b a vss vss nfet_03v3 w=1u l=.28u ad=2p as=1p pd=3u ps=2u\n.ends\n'
            extracted = '.subckt c a b vss\nX0 b.t a.t vss vss nfet_03v3 w=1u l=.28u ad=2p as=1p pd=3u ps=2u\nR0 b b.t 2\nR1 a a.t 3\nC0 b.t vss 1f\n.ends\n'
            p.write_text(original); q.write_text(extracted)
            self.assertEqual(rc_connectivity(p,q)['devices'],1)
            for bad in [extracted.replace('b.t a.t vss vss','b.t vss vss vss'),
                        extracted.replace('b.t a.t vss vss','b.t a.t vss a'),
                        extracted.replace('w=1u','w=2u'),
                        *[extracted.replace(k+'='+v,k+'=0') for k,v in [('ad','2p'),('as','1p'),('pd','3u'),('ps','2u')]],
                        extracted.replace('R1 a a.t 3','R1 a b 3'),
                        extracted.replace('R1 a a.t 3','R1 a a.t -3')]:
                q.write_text(bad)
                with self.assertRaises(ValueError): rc_connectivity(p,q)

    def test_mirrored_oracle_and_reset_window_pulses(self):
        case=next(c for c in inventory() if c['kind']=='reset' and not c['reverse'])
        v=case['corner'][3]
        rows=[]
        for ns in range(171):
            reset=ns<10 or 40<=ns<=60 or 110<=ns<=125
            r0=20<=ns<=90; r1=ns>=140
            g0=r0 and not reset; g1=r1 and not reset
            rows.append([ns*1e-9,r0*v,r1*v,reset*v,g0*v,g1*v,0,0,0,0])
        self.assertFalse(analyze(rows,case)['errors'])
        mirrored=[[r[i] for i in (0,2,1,3,5,4,7,6,9,8)] for r in rows]
        self.assertEqual(analyze(rows,case),analyze(mirrored,case|{'reverse':True}))
        rows[57][5]=v
        self.assertIn('MUTEX_RESET_SETTLED_OUTPUT_NOT_LOW',analyze(rows,case)['errors'])
        rows[57][5]=0; rows[58][5]=-v
        self.assertIn('MUTEX_ANALOG_OUTPUT_RAIL',analyze(rows,case)['errors'])

    def test_campaign_loads_exported_pins_and_uses_all_corners(self):
        cases = list(inventory())
        self.assertEqual(len(cases),len({json.dumps(c,sort_keys=True) for c in cases}))
        for corner in {c['corner'] for c in cases}:
            local = [c for c in cases if c['corner']==corner]
            self.assertEqual({c['kind'] for c in local},{'sequence','contention','reset','reset-contention'})
            self.assertTrue({(.05,.005),(.005,.05)} <= {c['loads'] for c in local})
        text,finish,step = deck(cases[0],Path('/models'),Path('/cell.spice'),Path('/wave'))
        self.assertIn('CG0 g0 0',text)
        self.assertIn('CG1 g1 0',text)
        self.assertIn('v(g0) v(g1)',text)
        self.assertEqual(finish,230)
        self.assertLess(step,.01)


if __name__=='__main__': unittest.main()
