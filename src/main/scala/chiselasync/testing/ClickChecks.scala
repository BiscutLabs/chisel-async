// SPDX-License-Identifier: Apache-2.0
package chiselasync.testing

/** Checks actual local register pins, including any injected distribution skew. */
private[testing] object ClickChecks {
  def apply(node: ujson.Value, pin: (ujson.Value,String) => String): Seq[String] = {
    node("timing").arr.filter(_("kind").str == "click-bundling-v1").flatMap { timing =>
      val cells=node("primitives").arr.map(p=>p("id").str->p).toMap
      val tag=node("rtl_path").str.replace('.','_')
      val fire=PinDelays.instance(cells("fire"))+".q"
      val t=timing("times")
      val common=s"""time ${tag}_fire_time=0;
always @(posedge $fire) ${tag}_fire_time=$$time;
"""
      val registers=Seq("input_phase","output_phase","payload").filter(cells.contains).map { id =>
        val trigger=pin(cells(id),"trigger"); val n=tag+"_"+id
        val data=if(id=="payload") pin(cells(id),"d") else ""
        val setup=if(id=="payload") s"""
    if (${n}_changed && $$time-${n}_data_time <= ${t("SETUP_FS").str}) $$fatal(1,"CLICK_SETUP $tag");
""" else ""
        val dataCheck=if(id=="payload") s"""time ${n}_data_time=0;
reg ${n}_changed=0;
always @($data or posedge reset) begin
  if (reset) ${n}_changed=0;
  else begin
    if (${n}_rise_seen && $$time-${n}_rise <= ${t("HOLD_FS").str}) $$fatal(1,"CLICK_HOLD $tag");
    ${n}_changed=1; ${n}_data_time=$$time;
  end
end
""" else ""
        s"""time ${n}_rise=0, ${n}_fall=0;
reg ${n}_rise_seen=0, ${n}_fall_seen=0;
$dataCheck
always @(posedge $trigger or posedge reset) begin
  if (reset) begin ${n}_rise_seen=0; ${n}_fall_seen=0; end
  else begin
    #0;
    if ($$time-${tag}_fire_time > ${t("CLOCK_SKEW_FS").str}) $$fatal(1,"CLICK_CLOCK_SKEW $tag $id");
    if (${n}_fall_seen && $$time-${n}_fall <= ${t("PULSE_LOW_FS").str}) $$fatal(1,"CLICK_PULSE_LOW $tag $id");
    $setup
    ${n}_rise=$$time; ${n}_rise_seen=1;
  end
end
always @(negedge $trigger) if (!reset && ${n}_rise_seen) begin
  if ($$time-${n}_rise <= ${t("PULSE_HIGH_FS").str}) $$fatal(1,"CLICK_PULSE_HIGH $tag $id");
  ${n}_fall=$$time; ${n}_fall_seen=1;
end
"""
      }
      val startup=if(timing("initial_token").bool) {
        val start=pin(cells("start_barrier"),"d")+"[1]"
        Seq(s"""reg ${tag}_started=0;
always @($start or reset) begin
  if(reset) ${tag}_started=0;
  else if($start) ${tag}_started=1;
  else if(${tag}_started) $$fatal(1,"CLICK_START_WITHDRAWN $tag");
end
""")
      } else Seq.empty
      Seq(common) ++ registers ++ startup
    }.toSeq
  }
}
