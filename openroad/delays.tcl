# Per cell output: the worst rise and fall delay into it over the cell's arcs,
# plus the worst wire delay from it to a load, in ps. Read on the loop-cut
# analysis netlist with the routed SPEF, where every arc has a delay.
foreach lib $::env(LIBERTY) { read_liberty $lib }
read_verilog $::env(NETLIST)
link_design $::env(TOP)
read_spef $::env(SPEF)
set_input_transition 0 [all_inputs]
set_cmd_units -time ps
report_checks -unconstrained -group_path_count 1 > /dev/null
set out [open $::env(OUT) w]
foreach inst [get_cells *] {
  foreach pin [get_pins -of_objects $inst -filter "direction == output"] {
    set rise 0; set fall 0
    foreach edge [get_timing_edges -to $pin] {
      set rise [expr {max($rise, [get_property $edge delay_max_rise])}]
      set fall [expr {max($fall, [get_property $edge delay_max_fall])}]
    }
    set wr 0; set wf 0
    set net [get_nets -quiet -of_objects $pin]
    if {$net ne ""} {
      foreach load [get_pins -quiet -of_objects $net -filter "direction == input"] {
        foreach edge [get_timing_edges -from $pin -to $load] {
          set wr [expr {max($wr, [get_property $edge delay_max_rise])}]
          set wf [expr {max($wf, [get_property $edge delay_max_fall])}]
        }
      }
    }
    puts $out "[get_full_name $inst]\t[get_property $pin lib_pin_name]\t[expr {$rise + $wr}]\t[expr {$fall + $wf}]"
  }
}
close $out
