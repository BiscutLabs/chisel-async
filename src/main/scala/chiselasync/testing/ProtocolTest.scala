// SPDX-License-Identifier: Apache-2.0
package chiselasync.testing

/** Protocol-specific event drivers and passive observers. Payload expectations are
  * supplied by the caller; none are derived from the circuit under test.
  */
private[testing] object ProtocolTest {
  val Four = "four-phase-bundled-v1"
  val Two = "two-phase-bundled-v1"
  val Dual = "dual-rail-rtz-v1"
  val supported = Set(Four, Two, Dual)
  final case class Channel(name: String, protocol: String, leaves: Seq[AsyncTest.Port]) {
    val dual: Boolean = protocol == Dual
    val width: Int = leaves.map(_.width).sum
    def signal(leaf: AsyncTest.Port, rail: String): String =
      if (dual) leaf.name.replace(s"${name}_bits", s"${name}_$rail") else leaf.name
    def packed(rail: String = "bits"): String = leaves.map(signal(_, rail)).mkString("{", ",", "}")
    def complete: String = if (dual) s"(&(${packed("zero")} ^ ${packed("one")}))" else s"${name}_req"
    def idle: String = if (dual) s"(({${packed("zero")},${packed("one")}}) == 0 && !${name}_ack)"
      else if (protocol == Two) s"(${name}_req == ${name}_ack)" else s"(!${name}_req && !${name}_ack)"
  }

  def channels(ports: Seq[AsyncTest.Port], protocols: Map[String, String]): Seq[Channel] =
    protocols.toSeq.sortBy(_._1).map { case (name, protocol) =>
      require(supported(protocol), s"ASYNC_TEST_UNSUPPORTED_PROTOCOL: $protocol")
      val field = if (protocol == Dual) "one" else "bits"
      val leaves = ports.filter(p => p.name == s"${name}_$field" || p.name.startsWith(s"${name}_${field}_"))
        .map(p => p.copy(name = p.name.replace(s"${name}_$field", s"${name}_bits")))
      require(leaves.nonEmpty, s"TEST_PAYLOAD_MISSING: $name")
      Channel(name, protocol, leaves)
    }

  def stimulus(context: AsyncTest.Context, inputs: Seq[AsyncTest.Input], outputs: Seq[AsyncTest.Output]): String = {
    val inventory = channels(context.ports, context.protocols).map(c => c.name -> c).toMap
    require((inputs.map(_.port) ++ outputs.map(_.port)).distinct.size == inputs.size + outputs.size, "DUPLICATE_TEST_CHANNEL")
    require((inputs.map(_.port) ++ outputs.map(_.port)).toSet == inventory.keySet, "TEST_CHANNEL_COVERAGE")
    (inputs.map(s => s.port -> s.layout) ++ outputs.map(s => s.port -> s.layout)).foreach { case (n, layout) =>
      if (layout.nonEmpty) require(layout == inventory(n).leaves.map(p => p.name -> (p.width, p.signed)).toMap,
        s"TEST_LITERAL_PORT_TYPE_MISMATCH: $n")
    }
    val rng = new scala.util.Random(context.seed)
    def pause: String = s"#${(1 + rng.nextInt(100)) * 1000000L};"
    def values(c: Channel, token: Map[String, BigInt], input: Boolean): Seq[(AsyncTest.Port, BigInt)] = {
      require(token.keySet == c.leaves.map(_.name).toSet, s"TEST_PAYLOAD_LEAVES: ${c.name}")
      c.leaves.map { p =>
        require(p.input == input && token(p.name) >= 0 && token(p.name) < (BigInt(1) << p.width), s"TEST_PAYLOAD_RANGE: ${p.name}")
        p -> token(p.name)
      }
    }
    def offer(c: Channel, token: Map[String, BigInt]): String = values(c, token, true).flatMap { case (p, v) =>
      if (c.dual) (0 until p.width).map { bit =>
        val rail = if (v.testBit(bit)) "one" else "zero"
        s"$pause ${c.signal(p, rail)}[$bit]=1;"
      } else Seq(s"${p.name}=${p.width}'h${v.toString(16)};")
    }.mkString("\n")
    def withdraw(c: Channel): String = c.leaves.flatMap(p => (0 until p.width).map { bit =>
      s"$pause ${c.signal(p, "zero")}[$bit]=0; ${c.signal(p, "one")}[$bit]=0;"
    }).mkString("\n")
    val writers = inputs.map { stream =>
      val c = inventory(stream.port); val n = c.name
      "begin\n" + stream.tokens.map { token =>
        val data = offer(c, token)
        if (c.dual) s"$pause\n$data\nwait (${n}_ack === 1'b1);\n${withdraw(c)}\nwait (${n}_ack === 1'b0);"
        else if (c.protocol == Two) s"$pause\n$data\n$pause ${n}_req=~${n}_req;\nwait (${n}_ack === ${n}_req);"
        else s"$pause\n$data\n$pause ${n}_req=1;\nwait (${n}_ack === 1'b1); $pause ${n}_req=0; wait (${n}_ack === 1'b0);"
      }.mkString("\n") + "\nend"
    }
    val readers = outputs.map { stream =>
      val c = inventory(stream.port); val n = c.name
      "begin\n" + stream.tokens.map { token =>
        val check = values(c, token, false).map { case (p, v) =>
          s"if (${c.signal(p, "one")} !== ${p.width}'h${v.toString(16)}) $$fatal(1,\"PAYLOAD_MISMATCH ${p.name}\");"
        }.mkString("\n")
        if (c.dual) s"wait (${c.complete} === 1'b1); $pause\n$check\n${n}_ack=1; wait ((${c.packed("zero")} | ${c.packed("one")}) === ${c.width}'d0); $pause ${n}_ack=0;"
        else if (c.protocol == Two) s"wait ((${n}_req ^ ${n}_ack) === 1'b1); $pause\n$check\n${n}_ack=${n}_req;"
        else s"wait (${n}_req === 1'b1); $pause\n$check\n${n}_ack=1; wait (${n}_req === 1'b0); $pause ${n}_ack=0;"
      }.mkString("\n") + "\nend"
    }
    "fork\n" + (writers ++ readers).mkString("\n") + "\njoin\n#1000000000;\n" +
      (inputs.map(s => s.port -> s.tokens.size) ++ outputs.map(s => s.port -> s.tokens.size)).map { case (n, size) =>
        s"if (delivered_$n != $size || !${inventory(n).idle}) $$fatal(1,\"TOKEN_COUNT_OR_IDLE $n\");"
      }.mkString("\n")
  }

  def monitor(c: Channel): String = {
    val n = c.name; val data = c.packed(); val w = c.width
    val header = s"integer delivered_$n = 0;\n"
    if (c.dual) {
      val z = c.packed("zero"); val o = c.packed("one")
      header + s"""reg returning_$n = 0;
reg [${w-1}:0] previous_zero_$n = 0, previous_one_$n = 0;
always @($z or $o or ${n}_ack or reset) begin
  #1;
  if (reset) begin returning_$n=0; previous_zero_$n=0; previous_one_$n=0; end
  else begin
    if ((^{$z,$o,${n}_ack}) === 1'bx) $$fatal(1,"UNKNOWN_RAIL $n");
    if (|($z & $o)) $$fatal(1,"ILLEGAL_DUAL_RAIL $n");
    if (!returning_$n) begin
      if (|(previous_zero_$n & ~$z) || |(previous_one_$n & ~$o)) $$fatal(1,"DUAL_RAIL_EARLY_WITHDRAW $n");
      if (${n}_ack) begin
        if (!(&($z ^ $o))) $$fatal(1,"DUAL_RAIL_EARLY_ACK $n");
        delivered_$n=delivered_$n+1; returning_$n=1;
      end
    end else begin
      if (|($z & ~previous_zero_$n) || |($o & ~previous_one_$n)) $$fatal(1,"DUAL_RAIL_NONMONOTONIC_RETURN $n");
      if (!${n}_ack) begin
        if (|($z | $o)) $$fatal(1,"DUAL_RAIL_EARLY_RETURN_ACK $n");
        returning_$n=0;
      end
    end
    previous_zero_$n=$z; previous_one_$n=$o;
  end
end
"""
    } else if (c.protocol == Two) {
      header + s"""reg old_req_$n=0, old_ack_$n=0;
reg [${w-1}:0] held_$n;
always @(${n}_req or ${n}_ack or $data or reset) begin
  #1;
  if (reset) begin old_req_$n=0; old_ack_$n=0; end
  else begin
    if ((^{${n}_req,${n}_ack}) === 1'bx) $$fatal(1,"UNKNOWN_HANDSHAKE $n");
    if (${n}_req != old_req_$n) begin
      if (old_req_$n != old_ack_$n || ${n}_ack != old_ack_$n) $$fatal(1,"HANDSHAKE_ORDER $n");
      if ((^$data) === 1'bx) $$fatal(1,"UNKNOWN_PAYLOAD $n");
      held_$n=$data;
    end
    if (${n}_ack != old_ack_$n) begin
      if (old_req_$n == old_ack_$n || ${n}_req != old_req_$n || ${n}_ack != ${n}_req) $$fatal(1,"HANDSHAKE_ORDER $n");
      delivered_$n=delivered_$n+1;
    end
    if (${n}_req != ${n}_ack && $data !== held_$n) $$fatal(1,"DATA_HOLD $n");
    old_req_$n=${n}_req; old_ack_$n=${n}_ack;
  end
end
"""
    } else header + s"""reg [1:0] state_$n = 0;
reg [${w-1}:0] held_$n;
always @(${n}_req or ${n}_ack or $data or reset) begin
  #1;
  if (reset) state_$n = 0;
  else begin
    if ((^{${n}_req,${n}_ack}) === 1'bx) $$fatal(1,"UNKNOWN_HANDSHAKE $n");
    if ({${n}_req,${n}_ack} != state_$n) begin
      case (state_$n)
        0: if ({${n}_req,${n}_ack} != 2) $$fatal(1,"HANDSHAKE_ORDER $n");
        2: if ({${n}_req,${n}_ack} != 3) $$fatal(1,"HANDSHAKE_ORDER $n");
        3: if ({${n}_req,${n}_ack} != 1) $$fatal(1,"HANDSHAKE_ORDER $n");
        1: if ({${n}_req,${n}_ack} != 0) $$fatal(1,"HANDSHAKE_ORDER $n");
      endcase
    end
    if (state_$n == 0 && ${n}_req) begin
      if ((^$data) === 1'bx) $$fatal(1,"UNKNOWN_PAYLOAD $n");
      held_$n = $data;
    end
    if (state_$n == 2 && {${n}_req,${n}_ack} == 3) delivered_$n = delivered_$n + 1;
    if ({${n}_req,${n}_ack} != 0 && state_$n != 0 && $data !== held_$n) $$fatal(1,"DATA_HOLD $n");
    state_$n = {${n}_req,${n}_ack};
  end
end
"""
  }
}
