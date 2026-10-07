# SPDX-License-Identifier: Apache-2.0
# Run in a fresh OpenSTA analysis context for a single loaded corner. Each path
# gets its own exceptions to avoid unrelated internal start/endpoints truncating it.
proc ca_measure {id arguments minimum maximum} {
  unset_path_exceptions {*}$arguments
  set_min_delay 0 {*}$arguments
  set_max_delay 1000000000 {*}$arguments
  set bounds {}
  foreach mode {min max} {
    set delays {}
    set starts {}; set ends {}
    foreach {flag objects} $arguments {
      if {$flag in {-from -rise_from -fall_from}} {
        foreach object $objects {
          set query $arguments
          dict set query $flag [list $object]
          set found [find_timing_paths {*}$query -path_delay $mode -group_path_count 100000 -endpoint_path_count 2]
          if {[llength $found] == 0} { error "TIMING_SOURCE_UNCOVERED: $id [get_full_name $object]" }
          # Path handles belong to this query. Extract values before the next
          # find_timing_paths call, which invalidates previous handles.
          foreach path $found {
            set points [get_property $path points]
            if {[llength $points] < 2} { error "TIMING_PATH_EMPTY: $id" }
            set first [lindex $points 0]; set last [lindex $points end]
            lappend starts [get_full_name [get_property $first pin]]
            lappend ends [get_full_name [get_property $last pin]]
            set delay [expr {[get_property $last arrival] - [get_property $first arrival]}]
            if {![string is double -strict $delay] || !($delay >= 0 && $delay < 1e9)} { error "INVALID_PATH_DELAY: $id" }
            lappend delays $delay
          }
        }
      }
    }
    if {[llength $delays] == 0} { error "TIMING_PATH_UNRESOLVED: $id $mode" }
    # Every bound bit must participate. Missing bits cannot pass on another bit's
    # slack. A disconnected/constant bit requires an explicit reviewed contract.
    foreach {flag objects} $arguments {
      if {$flag in {-to -rise_to -fall_to}} {
        foreach object $objects {
          if {[get_full_name $object] ni $ends} { error "TIMING_SINK_UNCOVERED: $id [get_full_name $object]" }
        }
      }
      if {$flag in {-from -rise_from -fall_from}} {
        foreach object $objects {
          if {[get_full_name $object] ni $starts} { error "TIMING_SOURCE_UNCOVERED: $id [get_full_name $object]" }
        }
      }
    }
    if {$mode eq "min"} { lappend bounds [tcl::mathfunc::min {*}$delays] } else { lappend bounds [tcl::mathfunc::max {*}$delays] }
  }
  unset_path_exceptions {*}$arguments
  return [ca_bounds $id $bounds $minimum $maximum]
}
# State cells may have characterized data/control arcs without a clocked timing
# path through the cell. Bind these to actual macro pins, not wrapper ports.
proc ca_arc {id sources sinks minimum maximum} {
  set lows {}; set highs {}; set covered {}
  foreach source $sources {
    set active 0
    foreach sink $sinks {
      foreach edge [get_timing_edges -from $source -to $sink] {
        foreach transition {rise fall} {
          set lo [get_property $edge delay_min_$transition]
          set hi [get_property $edge delay_max_$transition]
          if {![string is double -strict $lo] || ![string is double -strict $hi] ||
              !($lo >= 0 && $lo < 1e9 && $hi >= $lo && $hi < 1e9)} { error "INVALID_ARC_DELAY: $id" }
          lappend lows $lo; lappend highs $hi
        }
        set active 1
        lappend covered [get_full_name $sink]
      }
    }
    if {!$active} { error "TIMING_ARC_UNRESOLVED: $id [get_full_name $source]" }
  }
  foreach sink $sinks {
    if {[get_full_name $sink] ni $covered} { error "TIMING_SINK_UNCOVERED: $id [get_full_name $sink]" }
  }
  if {![llength $lows]} { error "TIMING_ARC_UNRESOLVED: $id" }
  return [ca_bounds $id [list [tcl::mathfunc::min {*}$lows] [tcl::mathfunc::max {*}$highs]] $minimum $maximum]
}
proc ca_bounds {id bounds minimum maximum} {
  lassign $bounds lo hi
  # Round conservatively to the contract's 1 fs precision.
  set lo [expr {floor($lo * 1e6) / 1e6}]
  set hi [expr {ceil($hi * 1e6) / 1e6}]
  if {$lo < $minimum} { error "TIMING_MIN_VIOLATION: $id measured=$lo required=$minimum" }
  if {$maximum ne "none" && $hi > $maximum} { error "TIMING_MAX_VIOLATION: $id measured=$hi required=$maximum" }
  puts "CA_TIMING_PATH id=$id min_ns=$lo max_ns=$hi"
  return [list $lo $hi]
}
proc ca_order {id early late margin} {
  set latest_early [expr {[lindex $early 1] + $margin}]
  set earliest_late [lindex $late 0]
  if {$latest_early >= $earliest_late} {
    error "TIMING_ORDER_VIOLATION: $id early=$latest_early late=$earliest_late"
  }
  puts "CA_TIMING_ORDER id=$id margin_ns=[expr {$earliest_late-$latest_early}]"
}
