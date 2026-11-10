# SPDX-License-Identifier: Apache-2.0
"""Run external GF180D layout checks. No tools or PDK are installed implicitly."""
import argparse
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

from characterize import sha
from layout import generate, HERE, TOP
from layout_checks import drc_report, lvs_log, rc_connectivity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--magic-pdk', type=Path, required=True)
    parser.add_argument('--pv-pdk', type=Path, required=True)
    parser.add_argument('--netgen-setup', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    for name in ('magic', 'klayout', 'netgen'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    out, pdk, pv = args.output.resolve(), args.magic_pdk.resolve(), args.pv_pdk.resolve()
    tools = {n: getattr(args,n).resolve() for n in ('magic','klayout','netgen')}
    inputs = [HERE/'mutex.spice', HERE/'layout.py', HERE/'layout_checks.py',
              HERE/'characterize.py', Path(__file__).resolve(), args.netgen_setup.resolve(),
              pdk/'gf180mcuD.tech', pdk/'gf180mcuD.tcl', pdk/'common.tcl']
    inputs += sorted((pv/'klayout').rglob('*.drc')) + sorted((pv/'klayout').rglob('*.lvs'))
    inputs += list(tools.values())
    hashes = {str(p): sha(p) for p in inputs}
    before = {p: (p.stat().st_size,p.stat().st_mtime_ns) for p in inputs}
    generate(out, pdk)
    empty_rc=out/'empty.magicrc'
    empty_rc.write_text('')
    receipt = dict(status='running', physical_qualification=False, inputs_sha256=hashes,
                   commands=[], results={}, exclusions=['density/fill', 'antenna',
                   'latch-up signoff', 'RC corners', 'electrical qualification'])
    try:
        def run(name, tool, options):
            command = [str(tools[tool]), *map(str, options)]
            log = out/(name+'.log')
            with log.open('w') as stream:
                r = subprocess.run(command, cwd=out, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
            receipt['commands'].append(dict(argv=command, returncode=r.returncode, log=str(log)))
            if r.returncode:
                raise ValueError('MUTEX_TOOL_FAILED:'+name)
            return log
        log = run('magic','magic',['-dnull','-noconsole','-rcfile',empty_rc,out/'layout.tcl'])
        text = log.read_text()
        if 'No errors found.' not in text or 'DRC_ERRORS \n' not in text:
            raise ValueError('MUTEX_MAGIC_DRC')
        # Upstream runner combines decks in this order. Retain all copyright text.
        rules = pv/'klayout/drc/rule_decks'
        pieces = [rules/'main.drc'] + [p for p in sorted(rules.glob('*.drc'))
            if p.name not in ('main.drc','tail.drc','layers_def.drc','antenna.drc','density.drc')] + [rules/'tail.drc']
        (out/'main.drc').write_text('\n'.join(p.read_text() for p in pieces))
        (out/'layers_def.drc').write_text((rules/'layers_def.drc').read_text())
        gds = out/(TOP+'.gds')
        common = ['metal_top=11K','metal_level=5LM','mim_option=B','verbose=true','thr=4',f'topcell={TOP}']
        def rd(values):
            return [a for v in values for a in ('-rd',str(v))]
        def drc(name, path):
            report = out/(name+'.lyrdb')
            run(name,'klayout',['-b','-r',out/'main.drc',*rd(common +
                [f'input={path}',f'report={report}','feol=true','beol=true','offgrid=true',
                 'conn_drc=true','density=false','run_mode=flat'])])
            return report
        receipt['results']['gds_drc'] = drc_report(drc('drc',gds))
        source = out/'schematic-mos.spice'
        def lvs(name, source):
            log = run(name,'klayout',['-b','-r',pv/'klayout/lvs/gf180mcu.lvs',*rd(common +
                [f'input={gds}',f'schematic={source}',f'report={out/(name+".lvsdb")}',
                 f'target_netlist={out/(name+".spice")}', 'poly_res=1k','mim_cap=2',
                 'run_mode=deep','lvs_sub=VSS','spice_net_names=true','schematic_simplify=true'])])
            return log
        lvs_log(lvs('lvs', source), 'klayout')
        run('netgen','netgen',['-batch','lvs',f'{out/(TOP+".spice")} {TOP}',
            f'{out/"schematic.spice"} {TOP}', args.netgen_setup.resolve(),out/'netgen-lvs.log'])
        lvs_log(out/'netgen-lvs.log','netgen')
        # Independent GDS geometry and DRC negative control, without changing the candidate.
        script = out/'geometry.py'
        script.write_text('''import json, pya
from pathlib import Path
layout=pya.Layout(); layout.read(input_gds)
cell=layout.cell(top_name)
b=cell.bbox(); u=layout.dbu
bbox=[b.left*u,b.bottom*u,b.right*u,b.top*u]
if bbox[0]<0 or bbox[1]<0 or bbox[2]>28 or bbox[3]>35.28:raise ValueError('MUTEX_OUTLINE_EXCEEDED')
Path(geometry_report).write_text(json.dumps(dict(bbox_um=bbox,outline_um=[28,35.28],area_mm2=28*35.28/1e6)))
cell.shapes(layout.layer(34,0)).insert(pya.Box(round(.1/u),round(17/u),round(1.1/u),round(17.05/u)))
layout.write(mutant_gds)
''')
        mutant_gds = out/'thin-wire.gds'
        run('geometry','klayout',['-b','-r',script,*rd([f'input_gds={gds}',f'top_name={TOP}',
            f'geometry_report={out/"gds-geometry.json"}',f'mutant_gds={mutant_gds}'])])
        report = drc('thin-wire',mutant_gds)
        faults = [n.findtext('category') for n in ET.parse(report).getroot().findall('./items/item')]
        if "'M1.1'" not in faults:
            raise ValueError('MUTEX_DRC_CONTROL_NOT_DETECTED')
        bad = out/'wrong-gate.spice'
        rows = source.read_text().splitlines()
        i = next(i for i,r in enumerate(rows) if r.startswith('M'))
        parts = rows[i].split(); parts[2] = 'VSS'; rows[i] = ' '.join(parts)
        bad.write_text('\n'.join(rows)+'\n')
        log = lvs('wrong-gate',bad)
        if "ERROR : Netlists don't match" not in log.read_text():
            raise ValueError('MUTEX_LVS_CONTROL_NOT_DETECTED')
        # Keep the unmerged 46-device view, all resistance splits and capacitances.
        head = '\n'.join((out/'layout.tcl').read_text().splitlines()[:6])
        (out/'rc.tcl').write_text(head + f'\nload {TOP}\nselect top cell\nextract all\n'
            'extresist all\next2spice lvs\next2spice hierarchy off\next2spice subcircuit top on\n'
            'ext2spice extresist on\next2spice cthresh 0\next2spice -o extracted-rc.spice\nquit -noprompt\n')
        run('rc','magic',['-dnull','-noconsole','-rcfile',empty_rc,out/'rc.tcl'])
        receipt['results']['rc_connectivity'] = rc_connectivity(out/(TOP+'.spice'),out/'extracted-rc.spice')
        receipt['results']['negative_controls'] = ['M1.1 thin wire', 'wrong MOS gate']
        receipt['results']['geometry'] = json.loads((out/'gds-geometry.json').read_text())
        receipt['status'] = 'pass'
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        receipt.update(status='fail', error=str(error))
    finally:
        if any(not p.is_file() or (p.stat().st_size,p.stat().st_mtime_ns)!=s for p,s in before.items()):
            receipt.update(status='fail', error='MUTEX_INPUT_CHANGED_DURING_RUN')
        receipt['outputs_sha256'] = {str(p): sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
        (out/'layout-report.json').write_text(json.dumps(receipt,indent=2)+'\n')
    raise SystemExit(0 if receipt['status']=='pass' else 1)


if __name__=='__main__':
    main()
