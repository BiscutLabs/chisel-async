# SPDX-License-Identifier: Apache-2.0
"""Experimental GF180D macro LEF from GDS. No accepted physical binding.

KLayout performs the geometry check; ordinary Python drives the optional tool.
M1--M4 are conservatively blocked. Top-metal pins are checked against the GDS.
"""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from characterize import sha
from layout import OUTLINE, TOP


def check_timing_point(report,kind,initial_state,input_slew_ns,load_pf,other_load_pf):
    """Reject unsupported scenario use; initial state still needs external proof.

    This is a characterization guard, not permission to adopt an arbiter model.
    Only measured grid points are admitted, without interpolation/extrapolation.
    """
    state={'idle':'both_low','reset':'retained_uncontended_winner'}
    if report['status']!='pass' or kind not in state or initial_state!=state[kind]:
        raise ValueError('MUTEX_TIMING_SCENARIO_PRECONDITION')
    def same(a,b):return math.isfinite(a) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-12)
    domain=report['domain']
    if not same(other_load_pf,domain['other_output_load_pf']) or not any(
        c['passed'] and c['kind']==kind and same(input_slew_ns,c['slew']*.6) and same(load_pf,c['load'])
        for c in report['cases']):
        raise ValueError('MUTEX_TIMING_OUTSIDE_MEASURED_DOMAIN')


def check_timing_inventory(report):
    from timing_views import cases, SLEWS, LOADS
    def key(c):return (tuple(c['corner']),c['side'],c['kind'],c['slew'],c['load'])
    expected={key(c) for c in cases()};actual=report['cases']
    if (report['status']!='pass' or {key(c) for c in actual}!=expected or
        len(actual)!=len(expected) or len({c['index'] for c in actual})!=len(actual) or
        not all(c['passed'] for c in actual)):
        raise ValueError('MUTEX_TIMING_INVENTORY')
    refined={key(c) for c in actual if c['corner'][0]=='ff_n40C_3v60' and
             c['slew']==min(SLEWS) and c['load']==max(LOADS)}
    fine=report.get('refinement',[]);by_key={key(c):c for c in actual}
    if {key(c) for c in fine}!=refined or len(fine)!=len(refined):
        raise ValueError('MUTEX_TIMING_REFINEMENT_INVENTORY')
    for c in fine:
        if not c['passed'] or c['step_scale']!=.5:raise ValueError('MUTEX_TIMING_REFINEMENT')
        coarse=by_key[key(c)]['measurements'];measured=c['measurements']
        metrics=['fall_delay_ns','fall_slew_ns']+(['rise_delay_ns','rise_slew_ns'] if c['kind']=='idle' else [])
        if any(not math.isfinite(measured[n]) or not math.isfinite(coarse[n]) or abs(measured[n]-coarse[n])>.005 for n in metrics):
            raise ValueError('MUTEX_TIMING_REFINEMENT')


def check_timing_binding(root,layout_report,timing_report):
    for name in ('extracted-rc.spice',TOP+'.spice'):
        path=root/name;digest=sha(path)
        if (layout_report['outputs_sha256'].get(str(path))!=digest or
            timing_report['inputs_sha256'].get(str(path))!=digest):
            raise ValueError('MUTEX_TIMING_LAYOUT_MISMATCH')


def pin_boxes(geometry):
    if tuple(geometry['outline_um']) != OUTLINE:
        raise ValueError('MUTEX_VIEW_OUTLINE')
    if set(geometry['ports']) != {'RESET','R0','R1','G0','G1','VDD','VSS'}:
        raise ValueError('MUTEX_VIEW_PORTS')
    if geometry.get('pin_layer') != 5 or geometry.get('pin_width_um') != .8:
        raise ValueError('MUTEX_VIEW_TOP_METAL_PINS')
    half=geometry['pin_width_um']/2
    pitch=geometry['pitch_um']
    return {n:[round(x*pitch-half,6),round(y*pitch-half,6),
               round(x*pitch+half,6),round(y*pitch+half,6)]
            for n,(x,y) in geometry['ports'].items()}


def lef(geometry):
    lines=['VERSION 5.8 ;','BUSBITCHARS "[]" ;','DIVIDERCHAR "/" ;',
           f'MACRO {TOP}','  CLASS BLOCK ;','  ORIGIN 0 0 ;',
           f'  SIZE {OUTLINE[0]} BY {OUTLINE[1]} ;']
    for name,box in pin_boxes(geometry).items():
        direction='OUTPUT' if name.startswith('G') and name!='VSS' else 'INPUT'
        use='POWER' if name=='VDD' else 'GROUND' if name=='VSS' else 'SIGNAL'
        if use!='SIGNAL':direction='INOUT'
        lines += [f'  PIN {name}',f'    DIRECTION {direction} ;',f'    USE {use} ;',
                  '    PORT','      LAYER Metal5 ;',
                  '      RECT '+' '.join(map(str,box))+' ;','    END',f'  END {name}']
    # No internal route is exposed as a routable signal pin.
    lines += ['  OBS']
    for layer in range(1,5):
        lines += [f'    LAYER Metal{layer} ;',f'    RECT 0 0 {OUTLINE[0]} {OUTLINE[1]} ;']
    return '\n'.join(lines+['  END',f'END {TOP}','END LIBRARY',''])


def gds_check(gds, geometry, report):
    import pya  # supplied only by the explicitly selected external KLayout
    layout=pya.Layout();layout.read(str(gds));cell=layout.cell(TOP)
    if cell is None:raise ValueError('MUTEX_VIEW_TOP_MISSING')
    u=layout.dbu
    def box(coords):return pya.Box(*(round(x/u) for x in coords))
    outline=pya.Region(box([0,0,*OUTLINE]))
    metals={i:pya.Region(cell.begin_shapes_rec(layout.layer(gds_layer,0)))
            for i,gds_layer in enumerate((34,36,42,46,81),1)}
    for layer,region in metals.items():
        if not (region-outline).is_empty():raise ValueError('MUTEX_VIEW_OUTSIDE_OUTLINE')
    # Check the pin rectangles against both real conductor geometry and GDS labels.
    labels={}
    for li in layout.layer_indices():
        it=cell.begin_shapes_rec(li)
        while not it.at_end():
            shape=it.shape()
            if shape.is_text():
                text=shape.text.transformed(it.trans())
                labels.setdefault(text.string,[]).append(text.trans.disp)
            it.next()
    pins=pin_boxes(geometry)
    covered=pya.Region()
    for name,coords in pins.items():
        rect=box(coords)
        covered.insert(rect)
        if not (pya.Region(rect)-metals[5]).is_empty():raise ValueError('MUTEX_VIEW_PIN_NOT_METAL:'+name)
        if not any(rect.contains(point) for point in labels.get(name,[])):
            raise ValueError('MUTEX_VIEW_PIN_LABEL:'+name)
    if not (metals[5]-covered).is_empty():raise ValueError('MUTEX_VIEW_UNBLOCKED_M5')
    Path(report).write_text(json.dumps(dict(status='pass',pins=pins,
        metal_area_um2={str(i):r.area()*u*u for i,r in metals.items()},
        outline_um=OUTLINE, access_not_yet_proven=True),indent=2)+'\n')


def access_fixture(geometry):
    """All pins connected: signals by detailed routing, supplies by M5 straps.

    The fixture tests access, not supply current capacity or IR drop. No cells or
    internal routes are omitted. A deliberately off-track macro origin exercises
    the landing pads rather than relying on a lucky alignment.
    """
    pins=pin_boxes(geometry);signals=set(pins)-{'VDD','VSS'}
    lines=['VERSION 5.8 ;','DIVIDERCHAR "/" ;','BUSBITCHARS "[]" ;',
           'DESIGN access ;','UNITS DISTANCE MICRONS 2000 ;',
           'DIEAREA ( 0 0 ) ( 240000 200000 ) ;','COMPONENTS 1 ;',
           f'- dut {TOP} + FIXED ( 80000 60000 ) N ;','END COMPONENTS',
           f'PINS {len(pins)} ;']
    positions={}
    for name,box in pins.items():
        x=220000 if name in ('R1','G1') else 20000
        y=round((30+(box[1]+box[3])/2)*2000);positions[name]=(x,y)
        use='POWER' if name=='VDD' else 'GROUND' if name=='VSS' else 'SIGNAL'
        direction='INOUT' if use!='SIGNAL' else 'OUTPUT' if name.startswith('G') else 'INPUT'
        lines.append(f'- {name} + NET {name} + DIRECTION {direction} + USE {use} '
            f'+ LAYER Metal5 ( -500 -500 ) ( 500 500 ) + FIXED ( {x} {y} ) N ;')
    lines+=['END PINS',f'NETS {len(signals)} ;']
    lines += [f'- {n} ( PIN {n} ) ( dut {n} ) + USE SIGNAL ;' for n in sorted(signals)]
    lines+=['END NETS','SPECIALNETS 2 ;']
    for n,use in [('VDD','POWER'),('VSS','GROUND')]:
        x,y=positions[n];end=round((40+(pins[n][0]+pins[n][2])/2)*2000)
        lines.append(f'- {n} ( PIN {n} ) ( dut {n} ) + USE {use} '
                     f'+ ROUTED Metal5 1600 ( {x} {y} ) ( {end} {y} ) ;')
    return '\n'.join(lines+['END SPECIALNETS','END DESIGN',''])


def route_script(out,tech):
    def q(p):
        value=p.as_posix()
        if any(c in value for c in '{}\n\r'):raise ValueError('UNSUPPORTED_TCL_PATH')
        return '{'+value+'}'
    return f'''read_lef {q(tech)}
read_lef {q(out/(TOP+'.lef'))}
read_def {q(out/'access.def')}
make_tracks
set_routing_layers -signal Metal4-Metal5
pin_access -min_access_points 1
# The coarse grid reports congestion on this tiny macro fixture. The final
# detailed route must still have zero violations and connect every signal.
global_route -allow_congestion
detailed_route -output_drc {q(out/'drc.rpt')}
set block [ord::get_db_block]
if {{[llength [$block getInsts]] != 1 || [llength [$block getNets]] != 7}} {{error "MUTEX_ACCESS_INVENTORY"}}
foreach net [$block getNets] {{
  if {{[llength [$net getITerms]] != 1 || [llength [$net getBTerms]] != 1}} {{error "MUTEX_ACCESS_CONNECTION"}}
  if {{[$net getSigType] == "SIGNAL"}} {{
    if {{[$net getWire] == "NULL"}} {{error "MUTEX_ACCESS_UNROUTED"}}
  }} else {{
    if {{[llength [$net getSWires]] != 1}} {{error "MUTEX_ACCESS_SUPPLY"}}
  }}
}}
write_def {q(out/'routed.def')}
write_db {q(out/'routed.odb')}
puts "MUTEX_ACCESS_PASS"
exit
'''


def check_tables(report_path,sta,out):
    """Compare OpenSTA's grid-point lookup with the SPICE measurements.

    The fixture's scenario is the characterized stimulus, NOT proof of a chip
    caller's state. No clock, resolution bound or synthesis function is added.
    """
    report=json.loads(report_path.read_text());root=report_path.parent
    check_timing_inventory(report)
    netlist=out/'timing.v'
    netlist.write_text(f'module top(input R0,R1,RESET, output G0,G1); {TOP} dut (.R0(R0),.R1(R1),.RESET(RESET),.G0(G0),.G1(G1)); endmodule\n')
    checks=[]
    for corner in sorted({c['corner'][0] for c in report['cases']}):
        library=root/(TOP+'__'+corner+'__scenarios.lib')
        if report['outputs_sha256'].get(str(library))!=sha(library):
            raise ValueError('MUTEX_VIEW_TIMING_TABLE_CHANGED')
        local=[c for c in report['cases'] if c['corner'][0]==corner]
        lines=[f'read_liberty {{{library.as_posix()}}}',f'read_verilog {{{netlist.as_posix()}}}','link_design top']
        for c in local:
            kind=c['kind'];side=c['side'];s=c['slew']*.6
            check_timing_point(report,kind,'both_low' if kind=='idle' else 'retained_uncontended_winner',s,c['load'],.05)
            source='R'+str(side) if kind=='idle' else 'RESET'
            lines+=['unset_case_analysis [get_ports {R0 R1 RESET}]',
                f'set_case_analysis 0 [get_ports R{1-side}]',
                'set_case_analysis '+('0 [get_ports RESET]' if kind=='idle' else f'1 [get_ports R{side}]'),
                f'set_input_transition {s} [get_ports {{R0 R1 RESET}}]',
                f'set_load {c["load"]} [get_ports G{side}]',f'set_load .05 [get_ports G{1-side}]',
                f'puts "BEGIN_{c["index"]}"',f'report_dcalc -from dut/{source} -to dut/G{side} -max -digits 9',
                f'puts "END_{c["index"]}"']
        path=out/(corner+'.tcl');path.write_text('\n'.join(lines+['exit','']))
        log=out/(corner+'.log')
        with log.open('w') as stream:
            result=subprocess.run([str(sta),'-exit',str(path)],stdout=stream,stderr=subprocess.STDOUT,timeout=60)
        text=log.read_text()
        if result.returncode or re.search(r'(?im)^\s*(error|warning):',text):
            raise ValueError('MUTEX_VIEW_LIBERTY_PARSE')
        for c in local:
            section=text.split(f'BEGIN_{c["index"]}\n')[-1].split(f'END_{c["index"]}\n')[0]
            delays=[float(x) for x in re.findall(r'(?m)^Delay = ([-+\d.eE]+)',section)]
            slews=[float(x) for x in re.findall(r'(?m)^Slew = ([-+\d.eE]+)',section)]
            edges=['rise','fall'] if c['kind']=='idle' else ['fall']
            expected_delay=[c['measurements'][e+'_delay_ns'] for e in edges]
            expected_slew=[c['measurements'][e+'_slew_ns'] for e in edges]
            if len(delays)!=len(edges) or len(slews)!=len(edges) or any(
                not math.isclose(a,b,rel_tol=2e-6,abs_tol=2e-6)
                for a,b in zip(delays+slews,expected_delay+expected_slew)):
                raise ValueError('MUTEX_VIEW_LIBERTY_LOOKUP:'+str(c['index']))
            checks.append(c['index'])
    return dict(grid_points_checked=len(checks),scope='scenario table lookup only')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--layout',type=Path,required=True)
    p.add_argument('--klayout',type=Path,required=True)
    p.add_argument('--openroad',type=Path,required=True)
    p.add_argument('--tech-lef',type=Path,required=True)
    p.add_argument('--timing-report',type=Path)
    p.add_argument('--sta',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if bool(a.timing_report)!=bool(a.sta):p.error('--timing-report and --sta are required together')
    root=a.layout.resolve();geometry=json.loads((root/'geometry.json').read_text())
    inputs=[Path(__file__).resolve(),Path(__file__).with_name('layout.py'),
            root/'geometry.json',root/(TOP+'.gds'),root/'layout-report.json',
            a.klayout.resolve(),a.openroad.resolve(),a.tech_lef.resolve()]
    if a.timing_report:
        inputs += [a.timing_report.resolve(),a.sta.resolve(),Path(__file__).with_name('timing_views.py'),
                   root/'extracted-rc.spice',root/(TOP+'.spice'),*sorted(a.timing_report.resolve().parent.glob('*.lib'))]
    receipt=dict(status='running',physical_qualification=False,inputs_sha256={str(x):sha(x) for x in inputs})
    try:
        checked=json.loads((root/'layout-report.json').read_text())
        if checked['status']!='pass':raise ValueError('MUTEX_VIEW_LAYOUT_UNCHECKED')
        for file in (root/'geometry.json',root/(TOP+'.gds')):
            if checked['outputs_sha256'].get(str(file))!=sha(file):
                raise ValueError('MUTEX_VIEW_LAYOUT_CHANGED')
        command=[str(a.klayout.resolve()),'-b','-r',str(Path(__file__).resolve()),
            '-rd',f'input_gds={root/(TOP+".gds")}',
            '-rd',f'geometry_json={root/"geometry.json"}',
            '-rd',f'geometry_report={out/"geometry-check.json"}']
        with (out/'geometry.log').open('w') as log:
            r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=60)
        receipt['command']=command
        if r.returncode:raise ValueError('MUTEX_VIEW_GDS_CHECK')
        result=json.loads((out/'geometry-check.json').read_text())
        if result['status']!='pass':raise ValueError('MUTEX_VIEW_GDS_CHECK')
        (out/(TOP+'.lef')).write_text(lef(geometry))
        (out/'access.def').write_text(access_fixture(geometry))
        (out/'route.tcl').write_text(route_script(out,a.tech_lef.resolve()))
        command=[str(a.openroad.resolve()),'-exit',str(out/'route.tcl')]
        with (out/'route.log').open('w') as log:
            routed=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        receipt['route_command']=command
        text=(out/'route.log').read_text()
        if routed.returncode or 'MUTEX_ACCESS_PASS' not in text or '[ERROR' in text:
            raise ValueError('MUTEX_VIEW_ROUTING_ACCESS')
        if (out/'drc.rpt').read_text().strip():raise ValueError('MUTEX_VIEW_ROUTE_DRC')
        if a.timing_report:
            check_timing_binding(root,checked,json.loads(a.timing_report.read_text()))
            receipt['timing_tables']=check_tables(a.timing_report.resolve(),a.sta.resolve(),out)
        receipt.update(status='pass',area_um2=OUTLINE[0]*OUTLINE[1],
                       results=result, routing_access=True,
                       exclusions=['full-chip route', 'supply integrity', 'timing', 'antenna', 'density'])
    except (ValueError,OSError,subprocess.TimeoutExpired) as error:
        receipt.update(status='fail',error=str(error))
    finally:
        if any(sha(x)!=receipt['inputs_sha256'][str(x)] for x in inputs):
            receipt.update(status='fail',error='MUTEX_VIEW_INPUT_CHANGED')
        receipt['outputs_sha256']={str(x):sha(x) for x in sorted(out.iterdir()) if x.is_file()}
        (out/'report.json').write_text(json.dumps(receipt,indent=2)+'\n')
    raise SystemExit(receipt['status']!='pass')


if __name__=='__main__':
    if 'input_gds' in globals():
        gds_check(input_gds,json.loads(Path(geometry_json).read_text()),geometry_report)
    else:main()
