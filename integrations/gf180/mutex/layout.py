# SPDX-License-Identifier: Apache-2.0
"""Experimental GF180 Mutex layout generator; no accepted physical binding.

Requires an externally prepared GF180D Magic technology/parameterized-cell set.
All placement/routing dimensions are micrometres. Outputs are reproducible source
collateral, not signoff evidence. Run DRC/LVS against the exported GDS separately.
"""
from pathlib import Path
import argparse, json, heapq

HERE=Path(__file__).resolve().parent
OUTLINE=(28.0,35.28)
TOP='ca_mutex_gf180_candidate'
PITCH=.7

def flatten(text):
    defs={};current=None
    for raw in text.splitlines():
        row=raw.strip().split()
        if not row or row[0].startswith('*'):continue
        if row[0].lower()=='.subckt':
            at=row.index('params:') if 'params:' in row else len(row)
            current=dict(ports=row[2:at],params=dict(x.split('=') for x in row[at+1:]),devices=[])
            defs[row[1]]=current
        elif row[0].lower()=='.ends':current=None
        elif row[0].startswith('X'):current['devices'].append(row)
        else:raise ValueError('UNSUPPORTED_SPICE:'+raw)
    result=[]
    def visit(name,path,binding,overrides):
        d=defs[name];params=d['params']|overrides
        def net(n):return binding.get(n,path+'_'+n)
        def param(v):return params[v[1:-1]] if v.startswith('{') else v
        for row in d['devices']:
            at=next((i for i,x in enumerate(row) if '=' in x),len(row));kind=row[at-1]
            args=[net(n) for n in row[1:at-1]];kw={k:param(v) for k,v in (x.split('=') for x in row[at:])}
            p=path+'_'+row[0]
            if kind in ('nfet_03v3','pfet_03v3'):
                result.append(dict(name=p.removeprefix('X_'),kind=kind,nodes=args,
                    w=float(kw['w'].removesuffix('u')),l=float(kw['l'].removesuffix('u'))))
            else:visit(kind,p,dict(zip(defs[kind]['ports'],args)),kw)
    visit(TOP,'X',dict(zip(defs[TOP]['ports'],defs[TOP]['ports'])),{})
    return result,defs[TOP]['ports']

def placement(devices):
    byname={d['name']:d for d in devices}
    out=[]
    for p in (False,True):
        t='XP' if p else 'XN'
        for side in (0,1):
            rows=[[f'XCORE{side}_{t}{i}' for i in range(3)]+[f'XFILTER_{t}{side}'],
                  [f'XCLEAR{side}_{t}{i}' for i in range(4)],
                  [f'XOUT{side}_{t}{i}' for i in range(2)]+[f'XOUT{side}_XDRIVE_{t}']]
            for row,names in enumerate(rows):
                y=([5,12,19] if not p else [30,36,43])[row]
                gate=4 if p and row==2 else 3
                for i,name in enumerate(names):
                    x=4*(i+1);x=40-x if side else x
                    out.append(byname[name]|dict(x=x,y=y,gate=gate,mirror=bool(side)))
        out.append(byname['XRESET_'+t]|dict(x=20,y=19 if not p else 43,gate=3,mirror=False))
    if len(out)!=len(byname) or {d['name'] for d in out}!=set(byname):
        raise ValueError('MUTEX_PLACEMENT_INVENTORY')
    return out

def route(terminals,order):
    owners={};paths={};pins={}
    for net,points in terminals.items():
        pins[net]=set(points)
        for point in points:
            if point in owners and owners[point]!=net:raise ValueError('PIN_CONFLICT:'+str(point))
            owners[point]=net
    def search(start,tree,net):
        def h(p):return min(abs(p[0]-t[0])+abs(p[1]-t[1])+3*abs(p[2]-t[2]) for t in tree)
        dist={start:0};prev={};q=[(h(start),0,start)]
        while q:
            _,cost,p=heapq.heappop(q)
            if dist[p]!=cost:continue
            if p in tree:
                path=[p]
                while p!=start:p=prev[p];path.append(p)
                return path[::-1]
            x,y,z=p
            for dx,dy,dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
                n=x+dx,y+dy,z+dz
                if not (1<=n[0]<=39 and 1<=n[1]<=49 and 0<=n[2]<3):continue
                if owners.get(n,net)!=net:continue
                step=4 if dz else 1
                if not dz and ((z%2==0 and dx) or (z%2==1 and dy)):step+=.2
                alt=cost+step
                if alt>=dist.get(n,float('inf')):continue
                dist[n]=alt;prev[n]=p;heapq.heappush(q,(alt+h(n),alt,n))
        raise ValueError('UNROUTABLE:'+net)
    for net in order:
        todo=sorted(pins[net]);tree={todo.pop(0)};edges=[]
        while todo:
            start=min(todo,key=lambda p:min(sum(abs(p[i]-t[i]) for i in range(3)) for t in tree))
            path=search(start,tree,net);edges.extend(zip(path,path[1:]))
            tree.update(path);todo.remove(start)
            for p in path:owners[p]=net
        paths[net]=edges
    return paths

def generate(out, pdk, source=None):
    source=source or HERE/"mutex.spice"
    devices,ports=flatten(source.read_text());placed=placement(devices)
    terminals={};lines=[]
    def point(net,x,y,z=0):terminals.setdefault(net,set()).add((x,y,z))
    def paint(layer,x0,y0,x1,y1):
        lines.extend([f'box values {x0:.4f}um {y0:.4f}um {x1:.4f}um {y1:.4f}um',f'paint {layer}'])
    def square(layer,x,y,w):paint(layer,x-w/2,y-w/2,x+w/2,y+w/2)
    def via(x,y,lower):
        for layer,w in [(f'metal{lower}',.4),(f'via{lower}',.26 if lower==1 else .28),(f'metal{lower+1}',.4)]:square(layer,x,y,w)
    def tcl_path(path):
        value=path.resolve().as_posix()
        if any(c in value for c in '{}\n\r'):raise ValueError('UNSUPPORTED_TCL_PATH')
        return '{'+value+'}'
    script=[f'tech load {tcl_path(pdk/"gf180mcuD.tech")}',
        'scalegrid 1 10','drc euclidean on',
        f'source {tcl_path(pdk/"gf180mcuD.tcl")}',
        f'source {tcl_path(pdk/"common.tcl")}',
        f'cd {tcl_path(out)}', 'load assembly -silent']
    device_scripts=[]
    paint('pwell',.7,.7,27.3,16.8);paint('nwell',.6,18.1,27.4,34.4)
    for d in placed:
        x,y=d['x']*PITCH,d['y']*PITCH
        params=f'w {d["w"]} l {d["l"]} guard 0 botc 0 gate_to_diffcont 0.56 gate_to_polycont {d["gate"]*PITCH-d["w"]/2:.3f}'
        device_scripts.extend([f'load mos_{d["name"]} -silent', 'box values 0 0 0 0',
            f'set p [dict merge [gf180mcu::{d["kind"]}_defaults] {{{params}}}]',
            f'gf180mcu::{d["kind"]}_draw $p', f'save mos_{d["name"]}'])
        cy=y+(d['gate']*PITCH+0.18-(d['w']/2+.22))/2
        lines.extend([f'box values {x}um {cy:.3f}um {x}um {cy:.3f}um',f'getcell mos_{d["name"]} child 0 0',f'identify {d["name"]}'])
        direction=-1 if d['mirror'] else 1
        for net,px,py in [(d['nodes'][0],d['x']+direction,d['y']),
                           (d['nodes'][2],d['x']-direction,d['y']),
                           (d['nodes'][1],d['x'],d['y']+d['gate'])]:
            point(net,px,py);via(px*PITCH,py*PITCH,1)
    # Shared body contacts, no per-transistor guard rings.
    for net,layer,ys in [('VSS','psubdiff',[1.4,16.1]),('VDD','nsubdiff',[18.9,33.6])]:
        for y in ys:
            for ix in (2,10,20,30,38):
                x=ix*PITCH;square(layer,x,y,.6);square(layer+'cont',x,y,.23);via(x,y,1)
                point(net,ix,round(y/PITCH))
    pincoords={'R0':(1,8),'R1':(39,8),'G0':(1,40),'G1':(39,40),'RESET':(20,24),'VSS':(1,1),'VDD':(1,49)}
    for name,(x,y) in pincoords.items():point(name,x,y,2)
    priority=['X_'+n for n in ['N0','N1','F0','F1','CLEAR0','CLEAR1','B0','B1','ENABLE']]
    if not set(priority)<=terminals.keys():raise ValueError('MUTEX_CRITICAL_ROUTE_BINDING')
    order=sorted(terminals,key=lambda n:(priority.index(n) if n in priority else len(priority),len(terminals[n]),n))
    paths=route(terminals,order)
    for net,edges in paths.items():
        for a,b in edges:
            if a[2]!=b[2]:via(a[0]*PITCH,a[1]*PITCH,min(a[2],b[2])+2)
            else:
                x0,x1=sorted((a[0]*PITCH,b[0]*PITCH));y0,y1=sorted((a[1]*PITCH,b[1]*PITCH))
                paint(f'metal{a[2]+2}',x0-.2,y0-.2,x1+.2,y1+.2)
    for net in sorted(terminals):
        if net not in ports:
            x,y,z=sorted(terminals[net])[0]
            square(f'metal{z+2}',x*PITCH,y*PITCH,.4)
            lines.append(f'label {net} center metal{z+2}')
    for i,name in enumerate(ports):
        x,y=pincoords[name]
        # Access from the chip's top-metal routing without entering the internal
        # M1--M4 obstruction. The original .4 um M4 landings were not routable
        # under via-in-pin constraints at arbitrary placement/track alignment.
        via(x*PITCH,y*PITCH,4)
        square('metal5',x*PITCH,y*PITCH,.8)
        lines.extend([f'label {name} center metal5',f'port make {i+1}'])
    script=script[:-1]+device_scripts+script[-1:]+lines+[f'flatten {TOP}',f'load {TOP}',f'select top cell',f'save {TOP}','drc check','drc catchup','puts "DRC_ERRORS [drc listall why]"',
        'extract all','ext2spice lvs','ext2spice hierarchy off','ext2spice subcircuit top on','ext2spice',f'gds write {TOP}.gds','quit -noprompt']
    out.mkdir(parents=True,exist_ok=False);(out/'layout.tcl').write_text('\n'.join(script)+'\n')
    (out/'placement.json').write_text(json.dumps(placed,indent=2));(out/'routes.json').write_text(json.dumps(paths,indent=2))
    flat=['.subckt '+TOP+' '+' '.join(ports)]
    flat += ['X'+d['name']+' '+' '.join(d['nodes'])+' '+d['kind']+f' w={d["w"]}u l={d["l"]}u' for d in devices]
    (out/'schematic.spice').write_text('\n'.join(flat+['.ends','']))
    (out/'schematic-mos.spice').write_text('\n'.join('M'+r[1:] if r.startswith('X') else r for r in flat+['.ends','']))
    (out/'geometry.json').write_text(json.dumps(dict(status='unqualified', outline_um=OUTLINE, area_mm2=OUTLINE[0]*OUTLINE[1]/1e6, ports=pincoords, pitch_um=PITCH, wire_width_um=.4, pin_width_um=.8, pin_layer=5),indent=2)+'\n')
    return dict(devices=len(placed),nets=len(terminals),edges=sum(map(len,paths.values())))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(generate(args.output.resolve(),args.pdk.resolve())))


if __name__=='__main__':main()
