# One clock; the period is the flow's CLOCK_PERIOD (ns, ps on asap7). The
# comparison reads the minimum period this design reaches: period - WNS.
create_clock -name clock -period $::env(CLOCK_PERIOD) [get_ports clock]
set_input_delay 0 -clock clock [delete_from_list [all_inputs] [get_ports clock]]
set_output_delay 0 -clock clock [all_outputs]
