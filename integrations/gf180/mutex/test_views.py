# SPDX-License-Identifier: Apache-2.0
"""Properties of experimental physical views; external PDK tools stay optional."""
import unittest
import tempfile

from characterize import CORNERS
from timing_views import LOADS, SLEWS, cases, check_wave, deck, liberty, measurements
from views import access_fixture, check_timing_binding, check_timing_inventory, check_timing_point, lef, pin_boxes, TOP
from characterize import sha
from pathlib import Path


GEOMETRY=dict(outline_um=[28,35.28],pin_layer=5,pin_width_um=.8,pitch_um=.7,
    ports={'R0':[1,8],'R1':[39,8],'G0':[1,40],'G1':[39,40],
           'RESET':[20,24],'VDD':[1,49],'VSS':[1,1]})


class ViewTests(unittest.TestCase):
    def test_top_pins_and_internal_obstructions_are_separate(self):
        pins=pin_boxes(GEOMETRY);text=lef(GEOMETRY)
        self.assertIn('CLASS BLOCK',text)
        self.assertNotIn('SITE ',text)
        obs=text.split('  OBS')[1]
        for layer in range(1,5):self.assertIn(f'LAYER Metal{layer}',obs)
        self.assertNotIn('Metal5',obs)
        for name,box in pins.items():
            self.assertTrue(0<=box[0]<box[2]<=28 and 0<=box[1]<box[3]<=35.28)
            port=text.split('  PIN '+name+'\n')[1].split('  END '+name)[0]
            self.assertIn('Metal5',port)
            self.assertIn('POWER' if name=='VDD' else 'GROUND' if name=='VSS' else 'SIGNAL',port)
        for bad in (GEOMETRY|{'pin_layer':4},GEOMETRY|{'outline_um':[29,35.28]},
                    GEOMETRY|{'ports':dict(R0=[1,8])}):
            with self.assertRaises(ValueError):pin_boxes(bad)

    def test_access_fixture_connects_supplies_without_changing_their_type(self):
        text=access_fixture(GEOMETRY)
        for name in GEOMETRY['ports']:
            self.assertIn(f'( PIN {name} ) ( dut {name} )',text)
        special=text.split('SPECIALNETS 2 ;')[1]
        self.assertIn('USE POWER + ROUTED Metal5',special)
        self.assertIn('USE GROUND + ROUTED Metal5',special)

    def test_characterization_grid_covers_both_scenarios_at_every_corner(self):
        inventory=list(cases())
        for corner in CORNERS:
            for side in (0,1):
                for kind in ('idle','reset'):
                    self.assertEqual({(c['slew'],c['load']) for c in inventory
                        if c['corner']==corner and c['side']==side and c['kind']==kind},
                        {(s,l) for s in SLEWS for l in LOADS})
        for case in inventory:
            text=deck(case,Path('/models'),Path('/cell'))
            self.assertIn('i(Vreq)' if case['kind']=='idle' else 'i(Vrst)',text)
            self.assertIn('CG0 g0 0',text);self.assertIn('CG1 g1 0',text)
            self.assertIn(f'VAL={.5*case["corner"][3]}',text)

    def test_missing_activity_or_failed_measurement_cannot_make_a_table(self):
        case=next(cases())
        values=dict(initial_g0=0,initial_g1=0,winner=3.3,loser_max=0,
                    final_g0=0,final_g1=0,q_input=-3.3e-14,idle_current=0,
                    rise_delay=1e-9,rise_slew=.2e-9,fall_delay=.7e-9,
                    fall_slew=.3e-9,q_fall=3.3e-14,fall_current=0)
        def log(v):return '\n'.join(f'{k} = {x:.9e}' for k,x in v.items())
        result=measurements(log(values),case)
        self.assertAlmostEqual(result['rise_delay_ns'],1)
        self.assertAlmostEqual(result['effective_input_cap_pf'],.01)
        for bad in (values|{'winner':0},values|{'initial_g1':3.3},values|{'loser_max':3.3},
                    {k:v for k,v in values.items() if k!='fall_delay'}):
            with self.assertRaises(ValueError):measurements(log(bad),case)
        with self.assertRaisesRegex(ValueError,'SIMULATION_ERROR'):
            measurements(log(values)+'\nError: measurement failed',case)

    def test_liberty_is_scenario_only_with_no_synthesis_function(self):
        corner=CORNERS[0]
        values=dict(rise_delay_ns=1,rise_slew_ns=.2,fall_delay_ns=.7,
                    fall_slew_ns=.3,effective_input_cap_pf=.01)
        results=[c|{'measurements':values} for c in cases() if c['corner']==corner]
        text=liberty(corner,results)
        self.assertIn('dont_use : true',text)
        self.assertIn('when : "!R1 & !RESET"',text)
        self.assertNotIn('function :',text);self.assertNotIn('ff (',text)
        self.assertNotIn('latch (',text)
        self.assertIn('max_transition : 3',text)
        self.assertIn('max_capacitance : 0.05',text)
        for bad in (results[:-1],results+[results[0]]):
            with self.assertRaisesRegex(ValueError,'GRID_INCOMPLETE'):liberty(corner,bad)

    def test_threshold_recrossing_cannot_be_published_as_propagation_delay(self):
        case=next(cases());v=case['corner'][3]
        rows=[[ns*1e-9,v if 20<=ns<55 else 0,0,0,v if 21<=ns<56 else 0,0]
              for ns in range(81)]
        check_wave(rows,case)
        # A low pulse followed by a valid final level used to pass the sparse
        # .meas endpoints and produce an incorrectly short table entry.
        rows[30][4]=0
        with self.assertRaisesRegex(ValueError,'RECROSSING'):check_wave(rows,case)

    def test_scenario_use_rejects_missing_state_and_unmeasured_domain(self):
        report=dict(status='pass',domain={'other_output_load_pf':.05},cases=[c|{'passed':True} for c in cases()])
        check_timing_point(report,'idle','both_low',.3,.02,.05)
        with self.assertRaisesRegex(ValueError,'PRECONDITION'):
            check_timing_point(report,'idle','other_request_low',.3,.02,.05)
        for slew,load,other in ((4,.02,.05),(.01,.02,.05),(.3,.1,.05),(.3,.001,.05),(.3,.02,.02),(.2,.02,.05)):
            with self.assertRaisesRegex(ValueError,'OUTSIDE_MEASURED_DOMAIN'):
                check_timing_point(report,'idle','both_low',slew,load,other)

    def test_timing_must_match_the_selected_extracted_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);paths=[root/n for n in ('extracted-rc.spice',TOP+'.spice')]
            for p in paths:p.write_text('circuit')
            hashes={str(p):sha(p) for p in paths}
            layout={'outputs_sha256':hashes};timing={'inputs_sha256':dict(hashes)}
            check_timing_binding(root,layout,timing)
            timing['inputs_sha256'][str(paths[0])]='old-layout-digest'
            with self.assertRaisesRegex(ValueError,'LAYOUT_MISMATCH'):check_timing_binding(root,layout,timing)

    def test_empty_or_partial_timing_inventory_is_not_a_pass(self):
        values=dict(rise_delay_ns=1,rise_slew_ns=.2,fall_delay_ns=.7,fall_slew_ns=.3)
        actual=[c|dict(index=i,passed=True,measurements=values) for i,c in enumerate(cases())]
        fine=[c|dict(step_scale=.5) for c in actual if c['corner'][0]=='ff_n40C_3v60'
              and c['slew']==min(SLEWS) and c['load']==max(LOADS)]
        report=dict(status='pass',cases=actual,refinement=fine)
        check_timing_inventory(report)
        for bad in ([],actual[:-1],actual+[actual[0]]):
            with self.assertRaisesRegex(ValueError,'INVENTORY'):check_timing_inventory(report|{'cases':bad})
        with self.assertRaisesRegex(ValueError,'REFINEMENT'):
            check_timing_inventory(report|{'refinement':fine[:-1]})


if __name__=='__main__':unittest.main()
