// SPDX-License-Identifier: Apache-2.0
// Independent path-checker fixture, not an asynchronous controller.
module Checker(input [1:0] a, output [1:0] z, output late, output disconnected);
  wire first;
  CA_TEST_BUF early_path (.A(a[0]), .Z(z[0]));
  CA_TEST_BUF other_bit (.A(a[1]), .Z(z[1]));
  CA_TEST_BUF late_first (.A(a[0]), .Z(first));
  CA_TEST_INV late_second (.A(first), .Z(late));
  assign disconnected = 1'b0;
endmodule
