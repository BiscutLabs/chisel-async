# SPDX-License-Identifier: Apache-2.0
"""Finite digital arbitration verification; not analog resolution qualification."""
def main():
    import collections
    import hashlib
    import json
    from pathlib import Path
    import subprocess

    import argparse
    from run import ROOT as REPO
    from compare_controllers import sha
    from campaign_environment import identity
    parser=argparse.ArgumentParser(description="Seeded MUTEX decisions, cancellation and reproducibility")
    parser.add_argument('--generated',type=Path,default=REPO/'target/generated')
    parser.add_argument('--output',type=Path,default=REPO/'target/verification/mutex')
    args=parser.parse_args();ROOT=args.output.resolve();ROOT.mkdir(parents=True,exist_ok=True)
    (ROOT/'report.json').write_text('{"status":"RUNNING"}\n',encoding='utf-8')
    environment=identity()
    iverilog='iverilog';vvp='vvp'
    source=ROOT/'ChiselAsyncMutex_v1.sv'
    source.write_bytes((args.generated.resolve()/'arbiter/ChiselAsyncMutex_v1.sv').read_bytes())
    template=REPO/'verification/mutex_random.sv'
    coverage=collections.defaultdict(set);latencies=set();summaries=[]
    for seed in [*range(1,33),0x80000000,0xffffffff]:
        logs=[]
        for noise in (0,1):
            out=ROOT/f'seed_{seed}_noise_{noise}';out.mkdir(exist_ok=True)
            cmd=[iverilog,'-g2012','-DCHISEL_ASYNC_MUTEX_TRACE','-s','MutexReview',
                 f'-PMutexReview.SEED={seed}',f'-PMutexReview.NOISE={noise}','-o',str(out/'sim.vvp'),
                 str(template),str(source)]
            c=subprocess.run(cmd,capture_output=True,text=True,timeout=30);(out/'compile.log').write_text(c.stdout+c.stderr,encoding='utf-8')
            assert c.returncode==0,c.stderr
            r=subprocess.run([vvp,str(out/'sim.vvp')],capture_output=True,text=True,timeout=10)
            (out/'simulation.log').write_text(r.stdout+r.stderr,encoding='utf-8')
            assert r.returncode==0 and r.stdout.splitlines().count('RANDOM_MUTEX_PASS')==1,(seed,noise,'\n'.join((r.stdout+r.stderr).splitlines()[-12:]))
            choices=[tuple(map(int,l.split('|')[1:])) for l in r.stdout.splitlines() if l.startswith('CHOICE|')]
            assert len(choices)==48
            assert [c[1:5] for c in choices[:24]]==[c[1:5] for c in choices[24:]],('RESET_REPRODUCIBILITY',seed)
            schedules={};commits=0
            for line in r.stdout.splitlines():
                fields=line.split('|')
                if fields[0]=='MUTEX_SCHEDULE':
                    _,instance,time,tag,candidate,latency=fields
                    assert 10<=int(latency)<=100
                    schedules[int(tag)]=(int(time),int(candidate),int(latency));latencies.add(int(latency))
                elif fields[0]=='MUTEX_COMMIT':
                    _,instance,time,tag,candidate=fields
                    when,value,delay=schedules[int(tag)]
                    assert int(time)==when+delay and int(candidate)==value
                    commits+=1
            assert commits>100
            for _,mode,_,winner,latency,_ in choices:coverage[mode].add(winner)
            logs.append(r.stdout)
        assert logs[0]==logs[1],('GLOBAL_RNG_INTERFERENCE',seed)
        summaries.append({'seed':seed,'status':'PASS','choices':48,'commits':commits,'schedules':len(schedules)})
    assert all(w=={1,2} for w in coverage.values())
    assert latencies==set(range(10,101)), 'RANDOM_RESOLUTION_COVERAGE'
    out={**environment,'status':'PASS','bench_sha256':sha(template),'checker_sha256':sha(Path(__file__)), 'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
         'seeds':summaries,'coverage':{str(k):sorted(v) for k,v in coverage.items()},
         'distinct_latencies':len(latencies),'min_observed_latency':min(latencies),'max_observed_latency':max(latencies)}
    (ROOT/'report.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8')
    print('PASS: 34 seeds x 2 global-RNG variants; both winners for simultaneous and both near-tie orders;')
    print('held grants, zero handover, contender cancellation, reset cancellation, reset reproducibility;')
    print('all 91 integral latencies observed' if len(latencies)==91 else f'{len(latencies)} distinct latencies observed')

if __name__=="__main__": main()
