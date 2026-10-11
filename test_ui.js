// Run: node test_ui.js
// Runs the page's own script against a tiny fake DOM and a fake API (ui_fixtures.json). No browser, no network.
const fs = require("fs"), vm = require("vm"), assert = require("assert");
const fx = JSON.parse(fs.readFileSync(__dirname + "/ui_fixtures.json", "utf8"));
const html = fs.readFileSync(__dirname + "/index.html", "utf8");
const script = fs.readFileSync(__dirname + "/app.js", "utf8");
assert.ok(html.includes('<script src="app.js"></script>') && !/<script>/.test(html), "index.html must load app.js and have no inline script");

class El {
  constructor(tag) { this.tag = tag; this.children = []; this.className = ""; this.dataset = {}; this.attrs = {};
    this._text = ""; this.listeners = {}; this.disabled = false; this.value = ""; this.title = "";
    const self = this;
    this.classList = {
      add(c) { if (!self.className.split(" ").includes(c)) self.className = (self.className + " " + c).trim(); },
      toggle(c, on) { const has = self.className.split(" ").includes(c); if (on && !has) this.add(c); if (!on && has) self.className = self.className.split(" ").filter(x => x !== c).join(" "); },
    };
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(""); }
  append(...n) { this.children.push(...n); }
  replaceChildren(...n) { this.children = n; this._text = ""; if (this.tag === "select") this.value = n.length ? n[0].value : ""; }
  setAttribute(k, v) { this.attrs[k] = v; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  all(tag) { return this.children.flatMap(c => [c, ...c.all(tag)]).filter(c => !tag || c.tag === tag); }
  querySelectorAll(sel) { return this.all(sel); }
}
const byId = {};
for (const m of html.matchAll(/id="([\w-]+)"/g)) { const tag = ["area", "day", "hour", "event"].includes(m[1]) ? "select" : m[1] === "go" || m[1].startsWith("tab-") ? "button" : "div"; byId[m[1]] = new El(tag); }
const document = { getElementById: id => byId[id], createElement: t => new El(t) };

const calls = [];
async function fetch(url, opts) {
  calls.push({ url, opts });
  const path = url.replace(/^.*?(\/(corridors|replays|check|feedback))/, "$1").split("?")[0];
  const body = path === "/corridors" ? fx.corridors : path === "/replays" ? fx.replays
    : path === "/check" ? (url.includes("mode=replay") ? fx.replay : fx.live) : path === "/feedback" ? { saved: true } : null;
  return { ok: body !== null, json: async () => body };
}
const tick = () => new Promise(r => setTimeout(r, 25));
const ctx = vm.createContext({ document, fetch, console, setTimeout });
vm.runInContext(script.replace('"REPLACE_WITH_YOUR_API_URL"', '"https://api.test"'), ctx);

(async () => {
  await tick();
  assert.strictEqual(byId.area.children.length, 8, "area list should have 8 areas");
  assert.ok(byId.event.children.length >= 1, "event list should have at least one replay");
  assert.strictEqual(byId.hour.children.length, 24);

  // live check
  byId.area.value = "behala"; byId.hour.value = "13";
  await byId.go.listeners.click[0](); await tick();
  let text = byId.result.textContent;
  for (const must of ["High risk", "Behala", "high tide", "Reported waterlogged here", "The whole day", "Did this area flood?", "Not a flood prediction"])
    assert.ok(text.includes(must), "live result is missing: " + must);
  assert.strictEqual(byId.result.all("div").filter(d => d.className.split(" ").includes("cell")).length, 24, "24 strip cells");
  assert.ok(calls.some(c => c.url.includes("/check?corridor=behala&mode=live&depart=")), "live URL shape");

  // feedback buttons are disabled for a future time (tomorrow) and enabled for a past one (today, hour 00)
  byId.day.value = byId.day.children[1].value; byId.hour.value = "13";
  await byId.go.listeners.click[0](); await tick();
  const future = byId.result.all("button"); assert.ok(future.length === 2 && future.every(b => b.disabled), "future hour: feedback disabled");
  byId.day.value = byId.day.children[0].value; byId.hour.value = "00"; await byId.go.listeners.click[0](); await tick();
  const past = byId.result.all("button"); assert.ok(past.length === 2 && past.every(b => !b.disabled), "past hour: feedback enabled");
  await past[0].listeners.click[0](); await tick();
  const fb = calls.filter(c => c.url.endsWith("/feedback")).pop();
  const sent = JSON.parse(fb.opts.body);
  assert.deepStrictEqual(Object.keys(sent).sort(), ["corridor", "depart", "flooded", "level"], "feedback sends only four fields");
  assert.strictEqual(sent.flooded, true);

  // replay tab
  await byId["tab-replay"].listeners.click[0]();
  assert.ok(!byId.evwrap.className.includes("hidden"), "event picker visible in replay mode");
  assert.strictEqual(byId.hour.value, "11", "replay default hour");
  await byId.go.listeners.click[0](); await tick();
  text = byId.result.textContent;
  assert.ok(text.includes("replay") && text.includes("understates"), "replay note shown");
  assert.ok(calls.some(c => c.url.includes("mode=replay&replay=dana-2024&depart=2024-10-25T11")), "replay URL shape");
  assert.ok(!byId.result.all("button").length, "no feedback buttons in replay");

  // back to live hides the event picker
  await byId["tab-live"].listeners.click[0]();
  assert.ok(byId.evwrap.className.includes("hidden"));
  console.log("UI test passed");
})().catch(e => { console.error("UI test FAILED:", e.message); process.exit(1); });
