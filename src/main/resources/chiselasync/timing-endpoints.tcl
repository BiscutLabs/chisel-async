# SPDX-License-Identifier: Apache-2.0
# OpenSTA handles bus brackets itself, including with -regexp. Query its native
# naming syntax and then require one exact full-name match (never a wildcard hit).
proc ca_exact {kind name} {
  set objects {}
  foreach object [get_${kind}s -quiet $name] {
    if {[get_full_name $object] eq $name} { lappend objects $object }
  }
  if {[llength $objects] != 1} { error "TIMING_ENDPOINT_UNRESOLVED: $kind $name" }
  if {[get_full_name [lindex $objects 0]] ne $name} { error "TIMING_ENDPOINT_AMBIGUOUS: $name" }
  return $objects
}
set_cmd_units -time ns
