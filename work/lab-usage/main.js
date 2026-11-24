import { View, div, svg } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { theme, machines, exec, appHome, readTextFile, checking, openOverlay, closeOverlay, props, shared, setShared } from "herdr";

function remaining(reset) {
  if (!Number.isFinite(reset)) return "Reset unavailable";
  const minutes = Math.ceil((reset * 1000 - Date.now()) / 60000);
  if (minutes <= 0) return "Reset pending";
  if (minutes >= 1440) return `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h`;
  return minutes >= 60 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`;
}

const MOD = "lab-weekly-usage";
const PROVIDERS = ["codex", "claude"];
const LABELS = {codex:"Codex", claude:"Claude Code"};
const REFRESH = MOD + ".refresh";

async function readConfig() {
  return {machine:"lab", python:"python3"};
}

function choice(provider) {
  const saved = shared(MOD + ".source." + provider);
  return saved?.host === null || typeof saved?.host === "string" ? saved.host : undefined;
}

function sourceHost(provider, config) {
  const override = choice(provider);
  return override === undefined ? config.machine : override;
}

function hostLabel(host) { return host === null ? "local" : host; }

function cacheKey(provider, host) {
  return MOD + ".quota." + provider + "." + JSON.stringify(host);
}

function cached(provider, host) {
  const current = shared(cacheKey(provider, host));
  if (current) return current;
  const old = shared(MOD + ".snapshot");
  const oldHost = old && "host" in old ? old.host : "lab";
  return oldHost === host && old?.[provider] ? {item:{...old[provider], at:old.at}} : {};
}

function reading(provider, incoming, previous, now) {
  if (incoming.status === 429) {
    const retries = (previous?.retries || 0) + 1;
    const delay = Math.max(Math.min(3600, 600 * 2 ** Math.min(retries - 1, 3)), incoming.retry_after || 0);
    return {...previous, ...incoming, next:now + delay, retries};
  }
  const next = provider === "claude" ? now + 300 : 0;
  if (incoming.code === "collector_unreachable") return {...previous, ...incoming, next, status:null, retries:0};
  return {...incoming, at:now, next, retries:0};
}

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
    this.panel = !props()?.sources && !props()?.details;
    this.hosts = {};
    this.request = shared(REFRESH);
    if (checking()) return;
    this.loadConfig(cx);
    cx.timer.every(this.panel ? 120000 : 60000, cx => this.loadConfig(cx));
    if (this.panel) cx.timer.every(60000, cx => cx.notify());
  }

  loadConfig(cx) {
    cx.spawn(async cx => {
      try {
        this.config = await readConfig();
        if (!this.config?.python || !(this.config.machine === null || typeof this.config.machine === "string")) {
          throw new Error("Invalid usage configuration");
        }
        this.configError = false;
        this.pollRequested = this.panel;
      } catch {
        this.config = null;
        this.configError = true;
      }
      cx.notify();
    });
  }

  refresh(cx, providers) {
    const now = Date.now() / 1000;
    const id = String(now) + "-" + Math.random();
    const groups = new Map();
    for (const provider of providers) {
      const host = sourceHost(provider, this.config);
      const last = cached(provider, host);
      if (last.item?.next > now || last.flight?.until > now) continue;
      setShared(cacheKey(provider, host), {...last, flight:{id, until:now + 35}});
      if (!groups.has(host)) groups.set(host, []);
      groups.get(host).push(provider);
    }
    if (!groups.size) return;
    const script = readTextFile(`${appHome()}/mods/${MOD}/collect.py`);
    for (const [host, batch] of groups) {
      cx.spawn(async cx => {
        let result;
        try {
          const source = await script;
          if (!source) throw new Error("Collector missing");
          const response = await exec(host === null ? this.config.python : "python3",
            ["-X", "utf8", "-c", source, ...batch], {on:host, timeout:25000});
          if (response.code === 0) result = JSON.parse(response.stdout);
        } catch {}
        for (const provider of batch) {
          const last = cached(provider, host);
          if (last.flight?.id !== id) continue;
          const entry = result?.[provider];
          const item = Number.isFinite(entry?.used) || typeof entry?.error === "string"
            ? entry : {error:"Check usage host", code:"collector_unreachable"};
          this.logResult(host, provider, item.code || (item.error ? "usage_unavailable" : "ok"));
          setShared(cacheKey(provider, host), {item:reading(provider, item, last.item, Date.now() / 1000)});
        }
        cx.notify();
      });
    }
  }

  logResult(host, provider, code) {
    if (code !== "ok") console.error(`[${MOD}] ${provider} ${code}`);
  }

  sources(t) {
    const choices = PROVIDERS.map(choice);
    const remotes = new Map(machines().filter(machine => typeof machine.name === "string")
      .map(machine => [machine.name, machine.layout]));
    for (const host of choices) {
      if (typeof host === "string" && !remotes.has(host)) remotes.set(host, "unavailable");
    }
    const rows = [undefined, null, ...remotes.keys()];
    return v_flex().size_full().p(16).gap(12).bg(t.popover).text_color(t.foreground).text_size(13)
      .child(div().font_semibold().child("Usage sources"))
      .child(h_flex().items_center().text_color(t.muted)
        .child(div().flex_1().child("Machine"))
        .children(PROVIDERS.map(provider => div().w(90).text_center().child(LABELS[provider]))))
      .child(v_flex().id("source-machines").min_h(0).flex_1().overflow_y_scroll().children(rows.map((host, row) => {
        const label = host === undefined ? `Install default (${hostLabel(this.config.machine)})` : hostLabel(host);
        const state = remotes.get(host);
        return h_flex().h(36).flex_none().gap(2).items_center()
          .child(div().flex_1().min_w(0).truncate().tooltip(label)
            .child(state && state !== "ready" ? label + " · " + state : label))
          .children(PROVIDERS.map((provider, column) => {
            const selected = choices[column] === host;
            return div().id(`source-${provider}-${row}`).w(88).py(4).rounded(5).text_center().cursor_pointer()
              .bg(selected ? t.selected : t.hover)
              .text_color(selected ? (provider === "codex" ? CODEX_COLOR : CLAUDE_COLOR) : t.muted)
              .hover(el => el.bg(t.selected)).tooltip(`${LABELS[provider]} · ${label}`)
              .on_click(() => setShared(MOD + ".source." + provider, host === undefined ? null : {host}))
              .child(selected ? "Selected" : "Select");
          }));
      })))
      .child(div().id("sources-close").cursor_pointer().on_click(() => closeOverlay(props().overlay)).child("Close"));
  }

  render(cx) {
    const t = theme();
    const data = {}, hosts = {};
    let busy = false;
    const request = shared(REFRESH);
    if (this.panel && !checking() && this.request !== request) {
      this.request = request;
      this.loadConfig(cx);
    }
    if (this.config) {
      const changed = [];
      for (const provider of PROVIDERS) {
        const host = sourceHost(provider, this.config);
        const state = cached(provider, host);
        data[provider] = state.item;
        hosts[provider] = host;
        if (state.flight?.until > Date.now() / 1000) busy = true;
        if (this.hosts[provider] !== host || this.pollRequested) changed.push(provider);
      }
      this.hosts = hosts;
      this.pollRequested = false;
      // The status bar owns collection so closing a popup cannot cancel the user's request.
      if (this.panel && changed.length) this.refresh(cx, changed);
    }
    const loading = this.configError ? "Check usage configuration" : "Loading…";
    if (props()?.sources) return this.config ? this.sources(t) : div().p(16).child(loading);
    const requestRefresh = () => setShared(REFRESH, String(Date.now()) + "-" + Math.random());
    if (props()?.details) {
      return v_flex().p(16).gap(12).bg(t.popover).text_color(t.foreground).text_size(13)
        .child(div().font_semibold().child("Usage"))
        .children(PROVIDERS.map(provider => {
          const item = data[provider], reset = item?.reset;
          const label = this.config ? `${LABELS[provider]} · ${hostLabel(hosts[provider])}` : LABELS[provider];
          return v_flex().gap(4)
            .child(div().font_semibold().text_color(provider === "codex" ? CODEX_COLOR : CLAUDE_COLOR).child(label))
            .child(div().child(!item ? loading : Number.isFinite(item.used) ? `${usagePercent(item)}% used · ${remaining(reset)}` : item.error))
            .when(item?.status===429, el=>el.child(div().text_color(t.muted).child(`Rate limited · retry ${remaining(item.next)}`)))
            .when(item?.code === "collector_unreachable" && Number.isFinite(item.used),
              el => el.child(div().text_color(t.muted).child(item.error + " · showing last reading")))
            .when(provider === "claude" && Number.isFinite(item?.used), el => el.child(div().text_color(FABLE_COLOR).child(item.fable ? `Fable ${usagePercent(item.fable)}% · ${remaining(item.fable.reset)}` : "Fable: unavailable")))
            .when(Number.isFinite(reset), el => el.child(div().text_color(t.muted).child(`Reset: ${new Date(reset * 1000).toLocaleString()}`)))
            .when(Number.isFinite(item?.at), el => el.child(div().text_color(t.dim).text_size(11).child(`Updated: ${new Date(item.at * 1000).toLocaleString()}`)));
        }))
        .child(div().text_color(t.dim).child("Codex every 2 min · Claude at least 5 min apart"))
        .child(h_flex().gap(20)
          .child(div().id("details-refresh").cursor_pointer().on_click(requestRefresh).child(busy ? "Loading…" : "Refresh"))
          .child(div().id("details-sources").cursor_pointer().on_click(() => {
            closeOverlay(props().overlay);
            openOverlay({mod:MOD, props:{sources:true}, kind:"popup", width:510, height:360});
          }).child("Sources"))
          .child(div().id("details-close").cursor_pointer().on_click(() => closeOverlay(props().overlay)).child("Close")));
    }
    const showDetails = () => openOverlay({ mod: MOD, props: { details: true }, kind: "popup", width: 510, height: 375 });
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
      .child(div().id("lab-refresh").cursor_pointer().tooltip("Refresh usage").on_click(requestRefresh).child(busy ? "…" : "↻"));
  }
}
