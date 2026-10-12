# Layout images of a routed chisel-async design: the whole die, and the same
# view with the library's primitives coloured by kind. Run with -gui offscreen.
read_db $::env(ODB)
gui::fit
gui::clear_highlights -1
gui::clear_selections
gui::set_display_controls "*" visible false
gui::set_display_controls "Layers/*" visible true
gui::set_display_controls "Nets/*" visible true
gui::set_display_controls "Nets/Power" visible false
gui::set_display_controls "Nets/Ground" visible false
gui::set_display_controls "Instances/*" visible true
gui::set_display_controls "Instances/Physical/*" visible false
gui::set_display_controls "Shape Types/*" visible true
gui::set_display_controls "Misc/Scale bar" visible true
save_image -width 1600 $::env(OUT_DIR)/routed.png

# Placement only, primitives coloured by kind (kinds.tcl from the export):
# C-elements, latches, matched delay lines and other control gates. The rest
# is the design's own logic, left uncoloured.
gui::set_display_controls "Shape Types/Routing/*" visible false
gui::set_display_controls "Layers/*" visible false
source $::env(KINDS)
set groups {celement 0 latch 1 delay 3 gate 5}
foreach inst [[ord::get_db_block] getInsts] {
  set name [$inst getName]
  foreach entry $ca_kinds {
    lassign $entry prefix kind
    if {[string match "${prefix}.variant_*" $name]} {
      gui::highlight_inst $name [dict get $groups $kind]
      break
    }
  }
}
save_image -width 1600 $::env(OUT_DIR)/primitives.png
exit
