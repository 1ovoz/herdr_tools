import { View, div, svg } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { theme, exec, appHome, readTextFile, checking, openOverlay, closeOverlay, props, shared, setShared } from "herdr";

function remaining(reset) {
  if (!Number.isFinite(reset)) return "Reset unavailable";
  const minutes = Math.ceil((reset * 1000 - Date.now()) / 60000);
  if (minutes <= 0) return "Reset pending";
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

function claudeResult(incoming, previous, now) {
  if (incoming.status !== 429) return { ...incoming, next:now+300, retries:0 };
  const retries=(previous?.retries||0)+1;
  const delay=Math.max(Math.min(3600,600*2**Math.min(retries-1,3)),incoming.retry_after||0);
  const last=Number.isFinite(previous?.used)?{used:previous.used,reset:previous.reset,fable:previous.fable}:{};
  return {...last,...incoming,next:now+delay,retries};
}

const USAGE_KEY="lab-weekly-usage.snapshot";
const IN_FLIGHT="lab-weekly-usage.in-flight";
const CODEX_COLOR = "#72ADFA";
const CLAUDE_COLOR = "#F0A477";
const FABLE_COLOR = "#C6A4F5";

function usagePercent(item) {
  return Number.isFinite(item?.used) ? Math.max(0, Math.min(100, item.used)) : null;
}

function meter(t, item, color, width, height) {
  const percent = usagePercent(item);
  return div().w(width).h(height).flex_none().rounded(height/2).overflow_hidden()
    .bg(t.hover || t.border)
    .when(percent > 0, bar => bar.child(div().w(width*percent/100).h_full().rounded(height/2).bg(color)));
}

function usageRow(t, label, item, color, compact = false) {
  const percent = usagePercent(item);
  const size = compact ? 10.1 : 11.5;
  const height = compact ? 11 : 16;
  const reset = percent !== null ? remaining(item.reset) : item?.status === 429 ? `Retry ${remaining(item.next)}` : item?.error || "—";
  return h_flex().h(height).gap(7).items_center().text_size(size).text_color(t.muted)
    .when(Boolean(label), row => row.child(div().w(12).flex_none().text_center().font_semibold().text_color(color).child(label)))
    .child(meter(t,item,color,compact?81:90,compact?4:6))
    .child(div().w(32).flex_none().text_right().text_color(t.foreground).child(percent===null ? "—" : `${percent}%`))
    .child(div().max_w(68).flex_none().truncate().child(reset));
}

export default class LabUsage extends View {
  init(_props, cx) {
    this.busy = false;
    this.snapshot = null;
    if (checking()) return;
    if (!props()?.details) {
      this.refresh(cx);
      cx.timer.every(120000, cx => this.refresh(cx));
    }
    cx.timer.every(60000, cx => cx.notify());
  }

  refresh(cx) {
    if (this.busy) return;
    const now=Date.now()/1000;
    if ((shared(IN_FLIGHT)||0)>now) return;
    setShared(IN_FLIGHT,now+30);
    this.busy = true;
    cx.spawn(async cx => {
      try {
        const source = await readTextFile(`${appHome()}/mods/lab-weekly-usage/collect.py`);
        if (!source) throw new Error("collector missing");
        const previous=shared(USAGE_KEY);
        const providers=(previous?.claude?.next||0)>now?["codex"]:["codex","claude"];
        const result = await exec("python3", ["-c", source,...providers], { on: "lab", timeout: 25000 });
        if (result.code !== 0) throw new Error("collector failed");
        const value = JSON.parse(result.stdout);
        if (!value.codex || providers.includes("claude")&&!value.claude) throw new Error("invalid response");
        this.snapshot = {...value,claude:value.claude?claudeResult(value.claude,previous?.claude,Date.now()/1000):previous?.claude};
      } catch {
        const previous=shared(USAGE_KEY);
        this.snapshot = { at: Date.now() / 1000, codex: { error: "Check lab connection" }, claude: previous?.claude||{error:"Check lab connection"} };
      } finally {
        setShared(USAGE_KEY, this.snapshot);
        setShared(IN_FLIGHT,0);
        this.busy = false;
        cx.notify();
      }
    });
  }

  render() {
    const t = theme(), data = shared(USAGE_KEY) || this.snapshot;
    if (props()?.details) {
      return v_flex().p(16).gap(14).bg(t.popover).text_color(t.foreground).text_size(13)
        .child(div().font_semibold().child("lab · Usage"))
        .children(["codex", "claude"].map(provider => {
          const item = data?.[provider], reset = item?.reset;
          return v_flex().gap(5)
            .child(div().font_semibold().text_color(provider === "codex" ? CODEX_COLOR : CLAUDE_COLOR).child(provider === "codex" ? "Codex" : "Claude Code"))
            .child(div().child(!item ? "Loading…" : Number.isFinite(item.used)?`${usagePercent(item)}% used · ${remaining(reset)}`:item.error))
            .when(item?.status===429,el=>el.child(div().text_color(t.muted).child(`Rate limited · retry ${remaining(item.next)}`)))
            .when(provider === "claude" && Number.isFinite(item?.used), el => el.child(div().text_color(FABLE_COLOR).child(item.fable ? `Fable ${usagePercent(item.fable)}% · ${remaining(item.fable.reset)}` : "Fable: unavailable")))
            .when(Number.isFinite(reset), el => el.child(div().text_color(t.muted).child(`Reset: ${new Date(reset * 1000).toLocaleString()}`)));
        }))
        .child(div().text_color(t.muted).child(data?.at ? `Updated: ${new Date(data.at * 1000).toLocaleString()}` : "Loading from lab…"))
        .child(div().text_color(t.dim).child("Codex every 2 min · Claude at least 5 min apart"))
        .child(h_flex().gap(20)
          .child(div().id("details-refresh").cursor_pointer().on_click((_e, cx) => this.refresh(cx)).child(this.busy ? "Loading…" : "Refresh"))
          .child(div().id("details-close").cursor_pointer().on_click(() => closeOverlay(props().overlay)).child("Close")));
    }
    const showDetails = () => openOverlay({ mod: "lab-weekly-usage", props: { details: true }, kind: "popup", width: 510, height: 340 });
    return h_flex().size_full().min_w(0).px(8).gap(8).items_center().justify_end().bg(t.chrome).border_t(1).border_color(t.border).text_size(11.5).text_color(t.muted)
      .child(h_flex().id("weekly-codex").gap(5).items_center().cursor_pointer().text_color(CODEX_COLOR)
        .tooltip("Codex usage details").on_click(showDetails)
        .child(svg("mods/lab-weekly-usage/codex.svg").size(15).flex_none())
        .child(usageRow(t,null,data?.codex,CODEX_COLOR)))
      .child(div().w(1).h(16).flex_none().bg(t.border))
      .child(h_flex().id("weekly-claude").gap(5).items_center().cursor_pointer().text_color(CLAUDE_COLOR)
        .tooltip("Claude and Fable usage details").on_click(showDetails)
        .child(svg("icons/claude.svg").size(15).flex_none())
        .child(v_flex().gap(2)
          .child(usageRow(t,"W",data?.claude,CLAUDE_COLOR,true))
          .child(usageRow(t,"F",data?.claude?.fable,FABLE_COLOR,true))))
      .child(div().id("lab-refresh").cursor_pointer().tooltip("Refresh usage").on_click((_e, cx) => this.refresh(cx)).child(this.busy ? "…" : "↻"));
  }
}
