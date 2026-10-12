# Keep every chisel-async primitive exactly as mapped: C-elements, latches and
# matched delay lines are not buffers to remove or gates to resize, and the
# wires between their cells are not nets to buffer. Nets on top-level ports
# stay free, so the resizer can still drive and buffer the design's inputs.
set ca_preserved 0
set ca_nets {}
foreach inst [[ord::get_db_block] getInsts] {
  if {[string match {*ca_primitive_*} [$inst getName]]} {
    $inst setDoNotTouch true
    incr ca_preserved
    foreach iterm [$inst getITerms] {
      set net [$iterm getNet]
      if {$net ne "NULL" && [$net getSigType] eq "SIGNAL" && [llength [$net getBTerms]] == 0} {
        dict set ca_nets [$net getName] $net
      }
    }
  }
}
if {$ca_preserved == 0} { error "CA_PRESERVE: no chisel-async primitive cells found" }
dict for {name net} $ca_nets { $net setDoNotTouch true }
puts "chisel-async: preserved $ca_preserved primitive cells and [dict size $ca_nets] nets"
