# SPDX-License-Identifier: Apache-2.0
"""Verify real deduplication and identical transaction contracts in both modes."""
import json
from pathlib import Path
import sys

from run import ROOT, read_sources
from run_architecture import execute
sys.path.insert(0, str(ROOT / "tools"))
from check_export import nodes, validate_export


def bench():
    connections = [".reset(reset)"]
    for lane in range(8):
        connections += [f".in_{lane}_req(req[{lane}])", f".in_{lane}_bits(data[{lane}])",
            f".in_{lane}_ack(ack[{lane}])", f".out_{lane}_req(offered[{lane}])",
            f".out_{lane}_bits(payload[{lane}])", f".out_{lane}_ack(taken[{lane}])"]
    return """module ArchitectureBench;
timeunit 1ns; timeprecision 1fs;
reg reset=1;
reg [7:0] req=0,taken=0;
wire [7:0] ack,offered;
reg [7:0] data[0:7]; wire [7:0] payload[0:7];
integer delivered[0:7];
ReplicatedExample dut(""" + ",".join(connections) + """);
initial begin for(integer i=0;i<8;i=i+1) begin data[i]=0; delivered[i]=0; end
  #1000; reset=0; end
for(genvar lane=0;lane<8;lane=lane+1) begin
  initial begin
    wait(!reset);
    for(integer token=0;token<64;token=token+1) begin
      #(1+lane%3); data[lane]=(token*17+lane*31)%256; req[lane]=1;
      wait(ack[lane]); #1; req[lane]=0; wait(!ack[lane]);
    end
  end
  initial begin
    wait(!reset);
    for(integer token=0;token<64;token=token+1) begin
      wait(offered[lane]); #(1+token%7);
      if(payload[lane] !== 8'((token*17+lane*31+lane%2)%256)) $fatal(1,"REPLICATION_PAYLOAD");
      if(!offered[lane]) $fatal(1,"REPLICATION_REQUEST_HOLD");
      delivered[lane]=delivered[lane]+1; taken[lane]=1;
      wait(!offered[lane]); #2; taken[lane]=0;
    end
  end
end
initial begin
  wait(delivered[0]==64 && delivered[1]==64 && delivered[2]==64 && delivered[3]==64 &&
       delivered[4]==64 && delivered[5]==64 && delivered[6]==64 && delivered[7]==64);
  wait(req==0 && ack==0 && offered==0 && taken==0); #100;
  if(req!==0 || ack!==0 || offered!==0 || taken!==0) $fatal(1,"REPLICATION_FINAL_IDLE");
  $display("ARCH_PASS replication lanes=8 delivered=512 final_idle=1"); $finish;
end
initial begin #100000; $fatal(1,"REPLICATION_DEADLINE"); end
endmodule
"""


def main():
    output = ROOT / "target/verification/optimized"
    output.mkdir(parents=True, exist_ok=True)
    report = output / "report.json"
    record = {"status": "RUNNING", "exports": {}, "cases": []}
    def save(): report.write_text(json.dumps(record, indent=2) + "\n")
    save()
    try:
        definitions = {}
        for name in ("replicated", "replicated_debug"):
            directory = ROOT / "target/generated" / name
            resolved = validate_export(directory)
            record["exports"][name] = resolved
            manifest = json.loads((directory / "contract.json").read_text())["manifest"]
            design_paths = [n["rtl_path"] for n in nodes(manifest["design"])]
            actual = {path: resolved["instances"][path] for path in design_paths}
            definitions[name] = len(set(actual.values()))
            if len(actual) != 25 or len(resolved["endpoints"]) != 240:
                raise RuntimeError("REPLICATION_INACTIVE_INVENTORY")
            record["cases"].append(execute(name, read_sources(directory), bench(), output/name))
        if definitions != {"replicated": 6, "replicated_debug": 25}:
            raise RuntimeError(f"DEDUPLICATION_NOT_OBSERVED: {definitions}")
        record.update(status="PASS", hardware_module_definitions=definitions,
                      scope="bounded functional/compiler experiment; not arbitrary equivalence or physical synthesis")
    except BaseException as error:
        record.update(status="ERROR", error=str(error)); save(); raise
    save()
    print(f"Optimized export PASS: {definitions}; 512 deliveries in each mode")


if __name__ == "__main__": main()
