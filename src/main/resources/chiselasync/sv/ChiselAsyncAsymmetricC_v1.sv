// SPDX-License-Identifier: Apache-2.0
// Atomic inertial n-ary asymmetric C-element; ideal forks and binary environment.
module ChiselAsyncAsymmetricC_v1 #(
  parameter integer COMMON=1, RISING=0, FALLING=0,
  parameter time DELAY_FS=0,
  parameter integer RESET_VALUE=0,
  parameter [COMMON-1:0] COMMON_INVERT=0,
  parameter [(RISING>0?RISING:1)-1:0] RISING_INVERT=0,
  parameter [(FALLING>0?FALLING:1)-1:0] FALLING_INVERT=0
)(input wire reset, input wire [COMMON-1:0] common,
  input wire [(RISING>0?RISING:1)-1:0] rising,
  input wire [(FALLING>0?FALLING:1)-1:0] falling,
  output wire q);
  timeunit 1fs;
  timeprecision 1fs;
  initial if (COMMON<1 || RISING<0 || FALLING<0 ||
              (RESET_VALUE!=0 && RESET_VALUE!=1) || DELAY_FS>64'h7fffffffffffffff)
    $fatal(1,"INVALID_ASYMMETRIC_C_PARAMETERS");
  // Rise when all common/rise inputs are 1. Fall when all common/fall
  // inputs are 0. Otherwise retain state. Do not decompose into binary cells.
  // Input bubbles belong INSIDE this atomic boundary, with no independent delay.
  wire [COMMON-1:0] c = common ^ COMMON_INVERT;
  wire [(RISING>0?RISING:1)-1:0] r = rising ^ RISING_INVERT;
  wire [(FALLING>0?FALLING:1)-1:0] f = falling ^ FALLING_INVERT;
  assign #(DELAY_FS) q = reset ? RESET_VALUE[0] :
    ((&c) & (RISING==0 ? 1'b1 : &r)) |
    (q & ((|c) | (FALLING==0 ? 1'b0 : |f)));
endmodule
