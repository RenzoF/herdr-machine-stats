// Machine stats: CPU, memory, disk and agents for this computer and every
// machine the app knows (machines()), one card each. Enter (or a double
// click) opens btop on the selected machine in a dialog. Opened as a dialog
// (mod.open:machine-stats) or as a tab (tab.new {mod: "machine-stats"}).
//
// Reads are read-only: one `sh -c` per machine through herdr-core, every
// POLL_MS. The same mod draws the btop dialog's title bar (props.btop).

import { View, div } from "gpui-kit";
import { v_flex, h_flex } from "gpui-base";
import {
  agents, terminals, machines, exec, hc, theme, settings, props, run,
  openOverlay, closeOverlay, nextCommand, notify, shared, setShared,
} from "herdr";
import {
  MOD, POLL_MS, STATUS_ORDER, readMachine, btopName, btopArgs, target,
  runAddress, hcErrorText, PENDING_KEY, abandoned, withoutLaunch,
  machineKey, agentsByMachine, cardLevel, band, sizeText, pushHistory,
  columnsFor, step, ageText,
} from "./stats.js";

const GLYPH = { blocked: "◐", working: "●", idle: "○", done: "✓" };
const PAD = 16;
const GAP = 10;
const SPARK_H = 14;

export default class MachineStats extends View {
  init(_props, cx) {
    const p = props() ?? {};
    if (p.btop) {
      // This dialog owns the terminal now: the launch is no longer pending.
      this.btop = p.btop;
      setShared(PENDING_KEY, withoutLaunch(shared(PENDING_KEY), p.name));
      return;
    }
    this.reads = new Map(); // machine key -> {snapshot, error, at, history}
    this.selected = 0;
    this.columns = 1;
    this.width = 0;
    this.btops = 0; // btop launches and dialogs from this copy, still open
    this.launching = new Map(); // name -> machine, while hc starts it
    this.handle = cx.focus_handle();
    this.focusSelf();
    // An overlay settles a moment after it opens; take the keyboard again.
    cx.timer.after(600, () => this.focusSelf());
    this.poll(cx);
    cx.timer.every(POLL_MS, (cx) => this.poll(cx));
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        this.command(command, cx);
        cx.notify();
      }
    });
  }

  // The btop terminal goes with its dialog, however that closes. A
  // dashboard closing while hc is still starting one ends it by name: no
  // dialog will ever show it.
  async close() {
    if (this.btop) {
      await hc(["kill", this.btop]);
      return;
    }
    this.closed = true;
    await Promise.all([...(this.launching ?? [])].map(([name, machine]) =>
      hc(["kill", target(machine, name)])));
  }

  // The keyboard, unless a btop of ours is (about to be) over this copy.
  focusSelf() {
    if (!this.btops) this.handle.focus();
  }

  // Ends launches that no dialog took over, then forgets them. close()
  // tries first, but a remote terminal may not exist yet when it runs,
  // and the app cancels the rest of the launch once the dashboard is gone.
  sweep(cx) {
    const old = abandoned(shared(PENDING_KEY), Date.now(), 60000);
    if (!old.length || this.sweeping) return;
    this.sweeping = true;
    cx.spawn(async () => {
      try {
        for (const p of old) await hc(["kill", target(p.machine, p.name)]);
        let left = shared(PENDING_KEY);
        for (const p of old) left = withoutLaunch(left, p.name);
        setShared(PENDING_KEY, left);
      } finally {
        this.sweeping = false;
      }
    });
  }

  // This computer first, then the others, as machines() orders them.
  // Before the app has read any (and under `herdr-app check`), just here.
  list() {
    const all = machines();
    return all.length ? all : [{ name: null, layout: "loading" }];
  }

  // One read per machine; a machine still answering the last one is left
  // alone, so a slow machine costs only its own card.
  poll(cx) {
    this.sweep(cx);
    for (const m of this.list()) {
      const key = machineKey(m.name);
      const read = this.reads.get(key) ?? { history: [] };
      this.reads.set(key, read);
      if (read.busy) continue;
      read.busy = true;
      cx.spawn(async (cx) => {
        const got = await readMachine(exec, m.name);
        read.busy = false;
        read.at = Date.now();
        read.snapshot = got.snapshot ?? null;
        read.error = got.error ?? null;
        if (got.snapshot) {
          read.history = pushHistory(read.history, got.snapshot.cpuPct);
        }
        cx.notify();
      });
    }
  }

  // Key commands: keys.json's "machine-stats.<command>", and "focus" when
  // the app hands this copy the keyboard (after the btop dialog closes).
  command(command, cx) {
    const [name, arg] = command.split(":");
    if (name === "focus") this.focusSelf();
    else if (name === "refresh") this.poll(cx);
    else if (name === "btop") {
      const all = this.list();
      const m = arg ? all.find((x) => (x.name ?? "here") === arg)
        : all[this.selected];
      if (m) this.openBtop(m, cx);
    }
  }

  // Agents per machine key, from the app's live lists.
  agentData() {
    return agentsByMachine(agents(), terminals());
  }

  label(m) {
    if (m.name) return m.name;
    return this.reads.get("")?.snapshot?.host ?? "this computer";
  }

  openBtop(m, cx) {
    const label = this.label(m);
    const name = btopName();
    // Pending until its dialog's title bar takes it over (see sweep).
    const pending = Array.isArray(shared(PENDING_KEY)) ? shared(PENDING_KEY)
      : [];
    setShared(PENDING_KEY,
      [...pending, { machine: m.name, name, at: Date.now() }]);
    this.launching.set(name, m.name);
    this.btops += 1;
    cx.spawn(async (cx) => {
      let result;
      try {
        result = await hc(btopArgs(m.name, name));
      } catch (error) {
        result = { code: -1, stderr: String(error?.message ?? error) };
      }
      this.launching.delete(name);
      const address = result.code === 0 ? runAddress(result.stdout) : null;
      if (this.closed) {
        // The dashboard went while hc was starting it (close() kills it by
        // name too, which can come too early): show nothing, leave nothing.
        if (address) await hc(["kill", address]);
        return;
      }
      if (!address) {
        this.btops -= 1;
        setShared(PENDING_KEY, withoutLaunch(shared(PENDING_KEY), name));
        notify({ title: `btop on ${label}`, level: "error",
          body: hcErrorText(result.stderr) });
        return;
      }
      openOverlay({
        kind: "dialog", width: 0.92, height: 0.9,
        layout: { type: "column", children: [
          { type: "block", size: { px: 34 }, content: { mod: MOD,
            props: { btop: address, name, machine: label } } },
          { type: "block", content: { terminal: address } },
        ] },
      });
      // Take the keyboard back once btop is gone (q, or the dialog's ✕):
      // first see it live (the list may lag the start by a moment), then
      // see it go.
      const live = () => terminals().some((x) => x.address === address &&
        x.state === "live");
      for (let i = 0; i < 20 && !live(); i++) await cx.sleep(250);
      while (live()) await cx.sleep(500);
      this.btops -= 1;
      this.focusSelf();
      cx.notify();
    });
  }

  key(event, cx) {
    const count = this.list().length;
    const k = event.key;
    if (k === "enter") this.command("btop", cx);
    else if (k === "r") this.poll(cx);
    else if (k === "q") {
      // Esc is the app's: it closes the top dialog by itself.
      const overlay = props()?.overlay;
      if (!overlay) return;
      closeOverlay(overlay);
    } else {
      const next = step(this.selected, k, count, this.columns);
      if (next === this.selected) return;
      this.selected = next;
    }
    cx.stop_propagation();
    cx.notify();
  }

  render() {
    const t = theme();
    if (this.btop) return this.titleBar(t);
    const list = this.list();
    this.selected = Math.min(this.selected, list.length - 1);
    const byMachine = this.agentData();
    // Until the first layout reports a size, lay out for a narrow dialog.
    const inner = Math.max(0, (this.width || 680) - 2 * PAD);
    this.columns = columnsFor(inner, list.length);
    const cardW = Math.floor((inner - GAP * (this.columns - 1)) /
      this.columns);
    const cards = list.map((m, i) => this.card(t, m, i, cardW,
      byMachine.get(machineKey(m.name))));
    return v_flex()
      .id("root")
      .track_focus(this.handle)
      .on_key_down((e, cx) => this.key(e, cx))
      .on_size_change((size, cx) => {
        this.width = size.width / (settings().zoom ?? 1);
        cx.notify();
      })
      .size_full()
      .p(PAD)
      .gap(12)
      .bg(t.background)
      .text_size(13)
      .text_color(t.foreground)
      .child(this.header(t, list, byMachine))
      .child(div().id("grid").flex_1().min_h(0).overflow_y_scrollbar()
        .child(h_flex().flex_wrap().items_stretch().gap(GAP).children(cards)))
      .child(div().text_size(11).text_color(t.dim).child(
        "←↓↑→ or h j k l move   Enter or double-click: btop   r refresh" +
        (props()?.overlay ? "   Esc close" : "")));
  }

  header(t, list, byMachine) {
    const levels = list.map((m) => this.level(m, byMachine));
    const down = levels.filter((l) => l === "down").length;
    const alert = levels.filter((l) => l === "alert").length;
    const parts = [`${list.length} machine${list.length === 1 ? "" : "s"}`];
    if (down) parts.push(`${down} down`);
    if (alert) parts.push(`${alert} alert${alert === 1 ? "" : "s"}`);
    const ats = list.map((m) => this.reads.get(machineKey(m.name))?.at)
      .filter(Boolean);
    const at = ats.length ? Math.min(...ats) : null;
    return h_flex().items_center().gap(10)
      .child(div().text_size(15).font_semibold().child("Machines"))
      .child(div().text_color(t.muted).child(parts.join(" · ")))
      .child(div().flex_1())
      .child(div().text_size(11).text_color(t.dim).child(
        at ? `updated ${ageText(Date.now() - at)}` : "reading…"));
  }

  level(m, byMachine) {
    const read = this.reads.get(machineKey(m.name));
    return cardLevel(read?.snapshot, byMachine.get(machineKey(m.name)));
  }

  card(t, m, i, width, agentsHere) {
    const read = this.reads.get(machineKey(m.name)) ?? {};
    const snap = read.snapshot;
    const level = cardLevel(snap, agentsHere);
    const selected = i === this.selected;
    const edge = selected ? t.accent
      : level === "down" ? t.ansi1 : level === "alert" ? t.ansi3 : t.border;
    const facts = snap
      ? `${snap.os} · ${snap.ncpu}c · load ${snap.load.toFixed(1)}` : "";
    const card = v_flex()
      .id(`card-${i}`)
      .w(width)
      .p(12)
      .gap(8)
      .rounded(8)
      .bg(t.surface)
      .border_1()
      .border_color(edge)
      .cursor_pointer()
      .on_click((e, cx) => {
        this.selected = i;
        this.handle.focus();
        if (e.click_count >= 2) this.openBtop(m, cx);
        cx.notify();
      })
      .child(h_flex().items_center().gap(8)
        .child(div().flex_none().size(8).rounded(4).bg(
          level === "down" ? t.ansi1 : level === "alert" ? t.ansi3 : t.ansi2))
        .child(div().min_w(0).truncate().font_semibold().child(this.label(m)))
        .when(!m.name, (el) => el.child(
          div().flex_none().text_size(11).text_color(t.dim).child("here")))
        .child(div().flex_1())
        .child(div().flex_none().text_size(11).text_color(t.muted)
          .child(facts)));
    if (!snap) return card.child(this.downLine(t, m, read));
    return card
      .child(this.gauge(t, "CPU", snap.cpuPct, this.spark(t, read.history)))
      .child(this.gauge(t, "MEM", snap.memPct,
        sizeText(snap.memUsedKb, snap.memTotalKb)))
      .child(this.gauge(t, "DISK", snap.diskPct,
        sizeText(snap.diskUsedKb, snap.diskTotalKb)))
      .child(this.agentLine(t, agentsHere))
      .children((agentsHere?.blocked ?? []).slice(0, 3)
        .map((a, j) => this.blockedRow(t, a, `${i}-${j}`)))
      .when((agentsHere?.blocked.length ?? 0) > 3, (el) => el.child(
        div().text_size(11).text_color(t.dim)
          .child(`+${agentsHere.blocked.length - 3} more need you`)));
  }

  downLine(t, m, read) {
    let text = "reading…";
    if (read.error) text = `down: ${read.error}`;
    else if (m.layout === "unavailable") text = "down: unavailable";
    return div().text_color(read.error || m.layout === "unavailable"
      ? t.ansi1 : t.dim).child(text);
  }

  bandColor(t, pct) {
    return { green: t.ansi2, yellow: t.ansi3, red: t.ansi1 }[band(pct)];
  }

  gauge(t, name, pct, tail) {
    const color = this.bandColor(t, pct);
    return h_flex().items_center().gap(8)
      .child(div().w(34).flex_none().text_size(11).text_color(t.muted)
        .child(name))
      .child(div().flex_1().h(8).rounded(4).bg(t.raised).overflow_hidden()
        .child(div().h_full().w(`${pct}%`).rounded(4).bg(color)))
      .child(h_flex().w(40).flex_none().justify_end().text_color(color)
        .child(`${pct}%`))
      .child(h_flex().w(72).flex_none().justify_end().text_size(11)
        .text_color(t.muted).child(tail));
  }

  // Recent CPU, oldest left, as thin bars in their bands' colours.
  spark(t, history) {
    return h_flex().h(SPARK_H).items_end().gap(1).children(
      (history ?? []).map((v) => div().w(2).flex_none()
        .h(Math.max(1, Math.round((v * SPARK_H) / 100)))
        .bg(this.bandColor(t, v))));
  }

  agentLine(t, here) {
    const counts = here?.counts ?? {};
    const shown = STATUS_ORDER.filter((s) => counts[s]);
    const row = h_flex().items_center().gap(12).text_size(12);
    if (!shown.length) {
      return row.child(div().text_color(t.dim).child("no agents"));
    }
    return row.children(shown.map((s) => h_flex().gap(4)
      .text_color(t[s] ?? t.muted)
      .child(GLYPH[s]).child(`${counts[s]} ${s}`)));
  }

  // An agent waiting on the person: click to go to it.
  blockedRow(t, a, id) {
    return h_flex()
      .id(`blocked-${id}`)
      .px(6)
      .py(2)
      .gap(6)
      .rounded(5)
      .text_size(12)
      .cursor_pointer()
      .hover((s) => s.bg(t.hover))
      .on_click((_e, cx) => {
        cx.stop_propagation();
        run("agent.focus", { terminal: a.address });
        const overlay = props()?.overlay;
        if (overlay) closeOverlay(overlay);
      })
      .child(div().flex_none().text_color(t.blocked).child(GLYPH.blocked))
      .child(div().min_w(0).truncate().child(a.label));
  }

  // The btop dialog's bar: what it is, and ✕.
  titleBar(t) {
    const { machine, overlay } = props() ?? {};
    return h_flex()
      .size_full()
      .px(12)
      .gap(10)
      .items_center()
      .bg(t.surface)
      .border_b(1)
      .border_color(t.border)
      .text_size(12)
      .child(div().font_semibold().text_color(t.foreground)
        .child(`btop · ${machine ?? ""}`))
      .child(div().text_color(t.dim).child("q quits"))
      .child(div().flex_1())
      .child(div()
        .id("close")
        .px(8)
        .py(2)
        .rounded(5)
        .text_color(t.muted)
        .cursor_pointer()
        .hover((s) => s.bg(t.hover).text_color(t.foreground))
        .on_click(() => closeOverlay(overlay))
        .child("✕"));
  }
}
