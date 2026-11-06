// Tests for app-mod/stats.js: node --test tests/js
// exec and hc are fakes; nothing here starts a program or reaches a core.

import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";

import {
  COLLECT_SCRIPT, BTOP_SCRIPT, HISTORY, btopArgs, runAddress, hcErrorText,
  parseSnapshot, rejectReason, exitReason, readMachine, machineOfAddress,
  agentsByMachine, cardLevel, band, sizeText, pushHistory, columnsFor, step,
  ageText,
} from "../../app-mod/stats.js";

const LINUX = `os=Linux
host=agent-desk
ncpu=24
load=10.41
cpu_pct=39
mem_total_kb=57554980
mem_avail_kb=21837404
disk_total_kb=312458220
disk_used_kb=115552376
disk_pct=38
`;

test("parseSnapshot reads the collector's facts", () => {
  const s = parseSnapshot(LINUX);
  assert.equal(s.os, "Linux");
  assert.equal(s.host, "agent-desk");
  assert.equal(s.ncpu, 24);
  assert.equal(s.load, 10.41);
  assert.equal(s.cpuPct, 39);
  assert.equal(s.memUsedKb, 57554980 - 21837404);
  assert.equal(s.memPct, 62);
  assert.equal(s.diskPct, 38);
  assert.equal(s.diskUsedKb, 115552376);
});

test("parseSnapshot names a missing or non-numeric fact", () => {
  assert.throws(() => parseSnapshot(LINUX.replace(/^ncpu=.*\n/m, "")),
    /lacks ncpu/);
  assert.throws(() => parseSnapshot(LINUX.replace("load=10.41", "load=")),
    /load is not a number/);
  assert.throws(() => parseSnapshot("ncpu=2\n"), /lacks os/);
  assert.throws(() => parseSnapshot(LINUX.replace("mem_total_kb=57554980",
    "mem_total_kb=0")), /no memory/);
});

test("parseSnapshot keeps percentages in 0..100", () => {
  const s = parseSnapshot(LINUX.replace("cpu_pct=39", "cpu_pct=104"));
  assert.equal(s.cpuPct, 100);
});

test("the collector script runs under sh here and parses", () => {
  const out = execFileSync("sh", ["-c", COLLECT_SCRIPT], { encoding: "utf8" });
  const s = parseSnapshot(out);
  assert.ok(s.ncpu >= 1);
  assert.ok(s.memTotalKb > 0);
  assert.ok(s.cpuPct >= 0 && s.cpuPct <= 100);
});

test("both scripts are valid sh", () => {
  for (const script of [COLLECT_SCRIPT, BTOP_SCRIPT]) {
    execFileSync("sh", ["-n", "-c", script]);
  }
});

test("the scripts keep awk's \\n escapes", () => {
  assert.match(COLLECT_SCRIPT, /printf "%\.0f %\.0f\\n"/);
  assert.match(COLLECT_SCRIPT, /cpu_pct=%d\\n/);
});

test("btopArgs starts btop with no parent, removed on exit", () => {
  const here = btopArgs(null);
  assert.deepEqual(here.slice(0, 7),
    ["run", "--bg", "--json", "--no-parent", "--rm", "--label",
      "by=machine-stats"]);
  assert.ok(!here.includes("--on"));
  assert.deepEqual(here.slice(-4), ["--", "sh", "-c", BTOP_SCRIPT]);
  const there = btopArgs("agent-desk");
  assert.equal(there[there.indexOf("--on") + 1], "agent-desk");
  assert.ok(there.indexOf("--on") < there.indexOf("--"));
});

test("runAddress and hcErrorText read hc's JSON", () => {
  assert.equal(runAddress('{"address":"agent-desk/t3s","state":"live"}'),
    "agent-desk/t3s");
  assert.equal(runAddress("not json"), null);
  assert.equal(hcErrorText(
    '{"error":{"kind":"machine_unknown","message":"unknown machine \\"x\\""}}'),
  'unknown machine "x"');
  assert.equal(hcErrorText("boom\nmore"), "boom");
  assert.equal(hcErrorText(""), "hc failed");
});

test("rejectReason shortens exec's rejections", () => {
  const e = (m) => new Error(m);
  assert.equal(rejectReason(e('`herdr.exec`: unknown machine "nosuch"')),
    "unknown machine");
  assert.equal(rejectReason(e("`herdr.exec`: machine agent-desk timed out")),
    "timeout");
  assert.equal(rejectReason(e("`herdr.exec`: agent-desk is unreachable")),
    "unreachable");
  assert.equal(rejectReason(e("`herdr.exec`: connection refused")),
    "unreachable");
  assert.equal(rejectReason(e(
    "`herdr.exec`: cannot start sh: No such file or directory (os error 2)")),
  "cannot start sh: No such file or directory (os error 2)");
  assert.equal(rejectReason("plain string"), "plain string");
  assert.ok(rejectReason(e("x".repeat(200))).length <= 60);
});

test("exitReason names a missing command", () => {
  assert.equal(exitReason(127, "sh: line 1: nproc: command not found\n"),
    "error: nproc not found");
  assert.equal(exitReason(127, "zsh:1: command not found: nproc"),
    "error: nproc not found");
  assert.equal(exitReason(127, "sh: 1: nproc: not found"),
    "error: nproc not found");
  assert.equal(exitReason(127, ""), "error: command not found");
  assert.equal(exitReason(3, "err\n"), "error: exit 3: err");
  assert.equal(exitReason(1, ""), "error: exit 1");
});

test("readMachine runs the collector there and never rejects", async () => {
  const calls = [];
  const fake = (result) => async (cmd, args, opts) => {
    calls.push([cmd, args, opts]);
    if (result instanceof Error) throw result;
    return result;
  };
  const ok = await readMachine(fake({ code: 0, stdout: LINUX, stderr: "" }),
    "agent-desk");
  assert.equal(ok.snapshot.host, "agent-desk");
  assert.deepEqual(calls[0], ["sh", ["-c", COLLECT_SCRIPT],
    { on: "agent-desk" }]);
  await readMachine(fake({ code: 0, stdout: LINUX, stderr: "" }), null);
  assert.equal(calls[1][2].on, null);

  assert.deepEqual(await readMachine(fake(new Error(
    '`herdr.exec`: unknown machine "x"')), "x"), { error: "unknown machine" });
  assert.deepEqual(await readMachine(fake(
    { code: 127, stdout: "", stderr: "sh: nproc: not found" }), "m"),
  { error: "error: nproc not found" });
  assert.match((await readMachine(fake(
    { code: 0, stdout: "os=Linux\n", stderr: "" }), "m")).error,
  /^unreadable output: collector output lacks ncpu/);
});

test("machineOfAddress splits remote addresses", () => {
  assert.equal(machineOfAddress("agent-desk/t7"), "agent-desk");
  assert.equal(machineOfAddress("t7"), "");
});

test("agentsByMachine counts agents and lists the blocked", () => {
  const agentList = [
    { address: "t1", status: "working", space_name: "shop", tab_name: "1" },
    { address: "agent-desk/t2", status: "blocked", space_name: "infra",
      tab_name: "deploy" },
    { address: "agent-desk/t10", status: "blocked", space_name: "vault",
      tab_name: "2" },
    { address: "agent-desk/t3", status: "done", space_name: "x",
      tab_name: "" },
    { address: "agent-desk/t4", status: "idle", space_name: "", tab_name: "",
      title: "Claude Code" },
  ];
  const terminalList = [
    // listed above: agents() wins over the raw word
    { address: "agent-desk/t2", state: "live", status: "idle" },
    // sub-agents: error is blocked, done is idle
    { address: "agent-desk/t9", state: "live", status: "error",
      name: "review" },
    { address: "t5", state: "live", status: "done" },
    // not counted: finished, no status, unknown word
    { address: "t6", state: "finished", status: "working" },
    { address: "t7", state: "live" },
    { address: "t8", state: "live", status: "weird" },
  ];
  const m = agentsByMachine(agentList, terminalList);
  assert.deepEqual(m.get("").counts, { working: 1, idle: 1 });
  assert.deepEqual(m.get("agent-desk").counts,
    { blocked: 3, done: 1, idle: 1 });
  assert.deepEqual(m.get("agent-desk").blocked.map((a) => a.label),
    ["infra · deploy", "vault", "review"]);
  assert.equal(m.get("agent-desk").blocked[0].address, "agent-desk/t2");
  assert.equal(m.get("omarchy-lenovo"), undefined);
  assert.equal(agentsByMachine([], []).size, 0);
});

test("cardLevel: down, alert, ok", () => {
  const snap = parseSnapshot(LINUX);
  assert.equal(cardLevel(null, undefined), "down");
  assert.equal(cardLevel(snap, undefined), "ok");
  assert.equal(cardLevel(snap, { counts: { blocked: 1 } }), "alert");
  assert.equal(cardLevel(snap, { counts: { working: 3 } }), "ok");
  assert.equal(cardLevel({ ...snap, diskPct: 91 }, undefined), "alert");
  assert.equal(cardLevel({ ...snap, memPct: 90 }, undefined), "ok");
});

test("band follows the TUI cards", () => {
  assert.equal(band(0), "green");
  assert.equal(band(59), "green");
  assert.equal(band(60), "yellow");
  assert.equal(band(84), "yellow");
  assert.equal(band(85), "red");
});

test("sizeText in G, and T from a thousand G", () => {
  const g = 1048576;
  assert.equal(sizeText(15 * g, 23 * g), "15/23G");
  assert.equal(sizeText(395.4 * g, 460.2 * g), "395/460G");
  assert.equal(sizeText(97387384, 1023483904), "93/976G");
  assert.equal(sizeText(512 * g, 2048 * g), "0.5/2.0T");
});

test("pushHistory keeps the latest samples", () => {
  let h;
  for (let i = 0; i < HISTORY + 5; i++) h = pushHistory(h, i);
  assert.equal(h.length, HISTORY);
  assert.equal(h[0], 5);
  assert.equal(h.at(-1), HISTORY + 4);
});

test("columnsFor fits cards of at least the minimum width", () => {
  assert.equal(columnsFor(0, 3), 1);
  assert.equal(columnsFor(650, 3), 2);
  assert.equal(columnsFor(1200, 3), 3);
  assert.equal(columnsFor(1200, 0), 1);
  assert.equal(columnsFor(200, 3), 1);
});

test("step moves by card and by row, staying on a card", () => {
  assert.equal(step(0, "right", 3, 2), 1);
  assert.equal(step(0, "l", 3, 2), 1);
  assert.equal(step(2, "right", 3, 2), 2);
  assert.equal(step(0, "left", 3, 2), 0);
  assert.equal(step(0, "down", 3, 2), 2);
  assert.equal(step(1, "j", 3, 2), 2);
  assert.equal(step(2, "up", 3, 2), 0);
  assert.equal(step(1, "k", 3, 2), 0);
  assert.equal(step(5, "x", 3, 2), 2);
  assert.equal(step(0, "down", 0, 1), 0);
});

test("ageText", () => {
  assert.equal(ageText(500), "just now");
  assert.equal(ageText(12000), "12s ago");
  assert.equal(ageText(185000), "3m ago");
  assert.equal(ageText(2 * 3600000), "2h ago");
});
