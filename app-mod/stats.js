// Machine stats without the app: the scripts run on each machine, what
// their output means, and the arithmetic the cards are drawn from. Nothing
// here imports "herdr" or "gpui-kit", so Node's test runner loads it as is.

// The mod's folder name under ~/.config/herdr-app/mods. The btop dialog's
// title bar is this mod again, so the link must use this name.
export const MOD = "machine-stats";

export const POLL_MS = 10000;
// CPU samples kept per machine: the sparkline's bars, 3 px each.
export const HISTORY = 24;
export const LIMIT_PCT = 90; // memory or disk above this is an alert
// Statuses in the order that matters to a person watching: stuck first.
export const STATUS_ORDER = ["blocked", "working", "idle", "done"];

// POSIX sh, run through `sh -c` on every machine (Linux and macOS). Prints
// key=value facts; parseSnapshot reads them. CPU is sampled over half a
// second on Linux and over one second by macOS's top. String.raw keeps
// awk's \n as two characters; the script has no ${, so nothing in it is
// JavaScript interpolation.
export const COLLECT_SCRIPT = String.raw`PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin
os=$(uname -s)
echo "os=$os"
echo "host=$(uname -n)"
if [ "$os" = Darwin ]; then
  echo "ncpu=$(sysctl -n hw.ncpu)"
  echo "load=$(sysctl -n vm.loadavg | awk '{print $2}')"
  top -l 2 -n 0 -s 1 |
    awk '/CPU usage/ {idle=$7} END {printf "cpu_pct=%d\n", 100 - idle + 0.5}'
  echo "mem_total_kb=$(( $(sysctl -n hw.memsize) / 1024 ))"
  vm_stat | awk '/page size of/ {ps=$8} /Pages free/ {n+=$3}
    /Pages inactive/ {n+=$3} /Pages speculative/ {n+=$3}
    END {printf "mem_avail_kb=%d\n", n*ps/1024}'
else
  echo "ncpu=$(nproc)"
  echo "load=$(cut -d' ' -f1 /proc/loadavg)"
  # printf, not print: mawk writes large counters as 9.67e+09.
  cpu() {
    awk '/^cpu / {printf "%.0f %.0f\n", $2+$3+$4+$5+$6+$7+$8+$9, $5+$6}' \
      /proc/stat
  }
  set -- $(cpu); total=$1 idle=$2; sleep 0.5; set -- $(cpu)
  busy=$(( ($1 - total) - ($2 - idle) )); span=$(( $1 - total ))
  [ "$span" -gt 0 ] || span=1
  echo "cpu_pct=$(( (100 * busy + span / 2) / span ))"
  awk '/^MemTotal:/ {print "mem_total_kb=" $2}
    /^MemAvailable:/ {print "mem_avail_kb=" $2}' /proc/meminfo
fi
df -Pk "$HOME" | awk 'NR==2 {print "disk_total_kb=" $2;
  print "disk_used_kb=" $3; gsub("%", "", $5); print "disk_pct=" $5}'
`;

// btop on the machine it runs on. A machine without btop says so for a few
// seconds before the terminal (and the dialog showing it) closes. Over a
// core connection there may be no UTF-8 locale, and btop refuses to start
// without one, so one is set when the current locale is not UTF-8:
// C.UTF-8 on Linux, en_US.UTF-8 on macOS (which has no C.UTF-8).
export const BTOP_SCRIPT = String.raw`PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin
loc=$LANG; [ -n "$LC_CTYPE" ] && loc=$LC_CTYPE; [ -n "$LC_ALL" ] && loc=$LC_ALL
utf=C.UTF-8; [ "$(uname -s)" = Darwin ] && utf=en_US.UTF-8
case "$loc" in
  *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
  *) export LANG=$utf; unset LC_ALL LC_CTYPE;;
esac
command -v btop >/dev/null && exec btop
echo "btop is not installed on $(uname -n)"; sleep 3
`;

// A name for one btop terminal, unique enough among live terminals
// (hc allows 1-32 of a-z 0-9 - _). Known before `hc run` returns, so a
// launch can be ended by name even if its reply never arrives.
export function btopName(random = Math.random) {
  return `${MOD}-btop-${random().toString(36).slice(2, 8).padEnd(6, "0")}`;
}

// The `hc run` arguments that start btop on `machine` (null: this one).
// No parent, so it belongs to nobody's tab; --rm, so it leaves nothing
// behind once it exits.
export function btopArgs(machine, name) {
  const on = machine ? ["--on", machine] : [];
  return ["run", "--bg", "--json", "--no-parent", "--rm", "--name", name,
    "--label", `by=${MOD}`, ...on, "--", "sh", "-c", BTOP_SCRIPT];
}

// How hc names a terminal on `machine` (null: this one).
export const target = (machine, name) => (machine ? `${machine}/${name}` : name);

// Launches no btop dialog has taken over, as kept in shared state:
// [{machine, name, at}]. Ones older than `ms` were abandoned (the
// dashboard closed while hc was still starting them) and get killed.
export const PENDING_KEY = `${MOD}.pending`;
// Twice exec's 30 s limit, so a launch hc is still starting never counts.
export const ABANDON_MS = 60000;
export function abandoned(pending, now, ms = ABANDON_MS) {
  return (Array.isArray(pending) ? pending : [])
    .filter((p) => p && typeof p.name === "string" && now - p.at > ms);
}
export function withoutLaunch(pending, name) {
  return (Array.isArray(pending) ? pending : []).filter((p) => p?.name !== name);
}
export function isPending(pending, name) {
  return (Array.isArray(pending) ? pending : []).some((p) => p?.name === name);
}

// After `hc kill` on an abandoned launch: forget it once hc says it is
// gone (killed, no such terminal, no such machine) or it is a day old;
// anything else (the machine unreachable) is tried again next poll.
const GONE = new Set([0, 3, 4]);
export function forgetLaunch(code, ageMs) {
  return GONE.has(code) || ageMs > 86400000;
}

// The address `hc run --json` printed, or null.
export function runAddress(stdout) {
  try {
    return JSON.parse(stdout).address ?? null;
  } catch {
    return null;
  }
}

// What hc said went wrong: its JSON error's message, else its first line.
export function hcErrorText(stderr) {
  try {
    const message = JSON.parse(stderr).error?.message;
    if (message) return message;
  } catch {
    // not JSON: fall through to the text
  }
  return (stderr ?? "").trim().split("\n")[0] || "hc failed";
}

const NUMBERS = ["ncpu", "load", "cpu_pct", "mem_total_kb", "mem_avail_kb",
  "disk_total_kb", "disk_used_kb", "disk_pct"];

// The facts in one machine's collector output. A missing or non-numeric
// fact throws an Error naming it.
export function parseSnapshot(text) {
  const facts = {};
  for (const line of text.split("\n")) {
    const at = line.indexOf("=");
    if (at > 0) facts[line.slice(0, at).trim()] = line.slice(at + 1).trim();
  }
  if (!facts.os) throw new Error("collector output lacks os");
  const n = {};
  for (const key of NUMBERS) {
    if (!(key in facts)) throw new Error(`collector output lacks ${key}`);
    const value = Number(facts[key]);
    if (facts[key] === "" || !Number.isFinite(value)) {
      throw new Error(`${key} is not a number: ${facts[key]}`);
    }
    n[key] = value;
  }
  if (n.mem_total_kb <= 0) throw new Error("collector reported no memory");
  const used = n.mem_total_kb - n.mem_avail_kb;
  return {
    os: facts.os,
    host: facts.host || null,
    ncpu: n.ncpu,
    load: n.load,
    cpuPct: clampPct(n.cpu_pct),
    memPct: clampPct(Math.round((100 * used) / n.mem_total_kb)),
    memUsedKb: used,
    memTotalKb: n.mem_total_kb,
    diskPct: clampPct(n.disk_pct),
    diskUsedKb: n.disk_used_kb,
    diskTotalKb: n.disk_total_kb,
  };
}

const clampPct = (v) => Math.max(0, Math.min(100, v));

// Why exec rejected: it could not start the program or reach the machine.
export function rejectReason(error) {
  const text = String(error?.message ?? error ?? "")
    .replace(/^`herdr\.exec`:\s*/, "").trim();
  if (/unknown machine/i.test(text)) return "unknown machine";
  if (/timed? ?out/i.test(text)) return "timeout";
  if (/unreachable|refused|no route|not connected|disconnected|offline/i
    .test(text)) return "unreachable";
  return short(text.split("\n")[0] || "cannot read");
}

// Why a read that ran exited `code`. A shell's "not found" names the
// missing command (zsh's wording first, then bash and dash).
const NOT_FOUND = [/command not found: (\S+)/,
  /([^\s:]+): (?:command )?not found/];
export function exitReason(code, stderr) {
  if (code === 127) {
    const hit = NOT_FOUND.map((p) => p.exec(stderr ?? "")).find(Boolean);
    return `error: ${hit ? hit[1] : "command"} not found`;
  }
  const first = (stderr ?? "").trim().split("\n")[0];
  return short(first ? `error: exit ${code}: ${first}` : `error: exit ${code}`);
}

function short(text, room = 60) {
  return text.length > room ? `${text.slice(0, room - 1)}…` : text;
}

// One read of one machine: {snapshot} or {error}, never a rejection.
// `exec` is herdr's (or a test's): exec(cmd, args, {on}).
export async function readMachine(exec, machine) {
  let result;
  try {
    result = await exec("sh", ["-c", COLLECT_SCRIPT], { on: machine });
  } catch (error) {
    return { error: rejectReason(error) };
  }
  if (result.code !== 0) return { error: exitReason(result.code, result.stderr) };
  try {
    return { snapshot: parseSnapshot(result.stdout) };
  } catch (error) {
    return { error: `unreadable output: ${error.message}` };
  }
}

// The machine an address lives on: "agent-desk/t7" is agent-desk's, a
// bare "t7" this machine's (""). Keys are strings so a Map can hold both.
export const machineKey = (name) => name ?? "";
export const machineOfAddress = (address) =>
  address.includes("/") ? address.slice(0, address.indexOf("/")) : "";

// What a sub-agent without a pane counts as: error is blocked, and done is
// idle (it reports to its parent, whose done is the news). As the shipped
// agents mod does.
const rawStatus = (s) => (s === "error" ? "blocked" : s === "done" ? "idle" : s);

// Agents per machine key: {counts: {status: n}, blocked: [agent]}.
// `agentList` is agents(): every agent with a pane, its status as the app
// shows it. Live terminals that report a status but aren't listed there
// (sub-agents) count too, by their own word.
export function agentsByMachine(agentList, terminalList = []) {
  const out = new Map();
  const add = (key, status, entry) => {
    if (!STATUS_ORDER.includes(status)) return;
    const m = out.get(key) ?? { counts: {}, blocked: [] };
    m.counts[status] = (m.counts[status] ?? 0) + 1;
    if (status === "blocked") m.blocked.push(entry);
    out.set(key, m);
  };
  const listed = new Set();
  for (const a of agentList) {
    listed.add(a.address);
    // A tab nobody named is called by its number: not worth showing.
    const tab = /^\d+$/.test(a.tab_name ?? "") ? "" : a.tab_name;
    add(machineOfAddress(a.address), a.status, {
      address: a.address,
      label: [a.space_name, tab].filter(Boolean).join(" · ") ||
        a.title || a.address,
    });
  }
  for (const t of terminalList) {
    if (t.state !== "live" || !t.status || listed.has(t.address)) continue;
    add(machineOfAddress(t.address), rawStatus(t.status), {
      address: t.address,
      label: t.name || t.labels?.where || t.address,
    });
  }
  return out;
}

// How a card is drawn: "down" (no reading), "alert" (an agent needs the
// person, or memory or disk is nearly full), or "ok".
export function cardLevel(snapshot, agents) {
  if (!snapshot) return "down";
  if (agents?.counts?.blocked) return "alert";
  return Math.max(snapshot.memPct, snapshot.diskPct) > LIMIT_PCT ? "alert" : "ok";
}

// A percentage's colour band, as the TUI cards: green, yellow, red.
export function band(pct) {
  if (pct < 60) return "green";
  return pct < 85 ? "yellow" : "red";
}

// "15/23G", or "1.2/3.6T" once the total reaches a thousand gigabytes.
export function sizeText(usedKb, totalKb) {
  const gib = 1048576;
  if (totalKb / gib >= 1000) {
    const tib = gib * 1024;
    return `${(usedKb / tib).toFixed(1)}/${(totalKb / tib).toFixed(1)}T`;
  }
  return `${Math.round(usedKb / gib)}/${Math.round(totalKb / gib)}G`;
}

// Recent CPU percentages, oldest first, at most HISTORY of them.
export function pushHistory(values, pct) {
  return [...(values ?? []), pct].slice(-HISTORY);
}

// Columns for `count` cards across `width` px, each at least `min` wide.
export function columnsFor(width, count, min = 300) {
  if (!width || count < 1) return 1;
  return Math.max(1, Math.min(count, Math.floor(width / min)));
}

// The selection after a key: arrows and h/j/k/l move by one card or one
// row, kept on a card. Unknown keys leave it where it is.
const MOVES = { left: -1, h: -1, right: 1, l: 1 };
export function step(selected, key, count, columns) {
  if (count < 1) return 0;
  let delta = MOVES[key];
  if (key === "up" || key === "k") delta = -columns;
  if (key === "down" || key === "j") delta = columns;
  if (delta === undefined) return Math.min(selected, count - 1);
  return Math.max(0, Math.min(count - 1, selected + delta));
}

// "just now", "12s ago", "3m ago".
export function ageText(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
}
