const API_BASE = "https://k2p0xwmb5j.execute-api.ap-south-1.amazonaws.com"; // no trailing slash, e.g. https://abc123.execute-api.ap-south-1.amazonaws.com
const USE_PHOTOS = false; // set to true after adding img/howrah-sunny.jpg and img/howrah-rain.jpg
let mode = "live";
let replays = [];
let last = null; // last result, used by the feedback buttons

const $ = (id) => document.getElementById(id);
const pad = (n) => String(n).padStart(2, "0");

function istNow(){
  const p = new Intl.DateTimeFormat("en-CA", {timeZone:"Asia/Kolkata", year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", hourCycle:"h23"}).formatToParts(new Date());
  const g = (t) => Number(p.find(x => x.type === t).value);
  return {y:g("year"), m:g("month"), d:g("day"), h:g("hour")};
}
function ymd(offset){
  const n = istNow(); const d = new Date(Date.UTC(n.y, n.m - 1, n.d + offset));
  return d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate());
}
function el(tag, cls, text){ const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function fillSelect(sel, items){ sel.replaceChildren(...items.map(([v, t]) => { const o = el("option", "", t); o.value = v; return o; })); }

function buildDayHour(){
  const n = istNow();
  fillSelect($("hour"), Array.from({length:24}, (_, h) => [pad(h), pad(h) + ":00"]));
  if (mode === "replay"){
    const ev = replays.find(r => r.id === $("event").value) || replays[0];
    if (!ev){ fillSelect($("day"), []); return; }
    fillSelect($("day"), ev.dates.map(d => [d, d]));
    $("day").value = ev.date; $("day").disabled = ev.dates.length < 2;
    $("hour").value = pad(ev.default_hour);
  } else {
    fillSelect($("day"), [[ymd(0), "Today"], [ymd(1), "Tomorrow"], [ymd(2), "Day after"]]); $("day").disabled = false;
    $("hour").value = pad(Math.min(23, n.h + 1));
  }
}

async function api(path, opts){
  if (API_BASE.indexOf("REPLACE_WITH") === 0) throw new Error("This page has no API address yet. Open index.html in a text editor, replace REPLACE_WITH_YOUR_API_URL with your API Gateway Invoke URL (https://...amazonaws.com, no slash at the end), and save. Until then the page cannot load areas or forecasts.");
  const r = await fetch(API_BASE + path, opts);
  let body = null; try { body = await r.json(); } catch (e) {}
  if (!r.ok) throw new Error((body && body.error) || "The service did not respond. Try again in a minute.");
  return body;
}

async function loadAreas(){
  try {
    const areas = await api("/corridors");
    fillSelect($("area"), areas.map(a => [a.id, a.name]));
    replays = await api("/replays");
    fillSelect($("event"), replays.map(r => [r.id, r.name]));
  } catch (e) { showError(e.message); }
}


function setSky(res, depart){
  const h = Number(depart.slice(11)), cell = (res.strip || []).find(c => c.hour === h);
  const rain = cell && cell.rain !== null && cell.rain !== undefined ? cell.rain : null;
  let s = "idle";
  if (rain !== null) s = rain >= 15 ? "heavy" : rain >= 5 ? "steady" : rain >= 1 ? "light" : (h >= 6 && h < 18 ? "sun" : "night");
  $("sky").dataset.sky = s; $("sky").dataset.photo = USE_PHOTOS ? "1" : "0";
}
function resetSky(){ $("sky").dataset.sky = "idle"; }
function showError(msg){ $("result").replaceChildren(el("div", "err", msg)); }

function render(res, depart){
  const box = el("div");
  const verdict = el("div", "verdict"); verdict.dataset.level = res.level;
  const staff = el("div", "staff"); staff.dataset.level = res.level; staff.setAttribute("aria-hidden", "true");
  staff.append(el("i"), el("i"), el("i"));
  const t = el("div");
  t.append(el("p", "level", res.level), el("p", "sub", res.area + ", leaving around " + depart.slice(11) + ":00" + (res.mode === "replay" ? " (replay)" : "")));
  verdict.append(staff, t); box.append(verdict);

  const ul = el("ul", "why"); res.reasons.forEach(r => ul.append(el("li", "", r))); box.append(ul);
  if (res.history && res.history.length) box.append(el("p", "hint", "Reported waterlogged here: " + res.history.join("; ") + ". This is shown for context and does not change the level."));
  if (res.better_time) box.append(el("p", "better", "Try instead: " + res.better_time + "."));

  box.append(el("h2", "", "The whole day"));
  box.append(el("p", "hint", "Each bar is a departure hour. Taller means higher risk. The blue triangle marks a high tide at Garden Reach" + (res.high_tides.length ? " (" + res.high_tides.join(", ") + ")." : ". No tide table is loaded for this date.")));
  const strip = el("div", "strip"); strip.setAttribute("role", "img");
  strip.setAttribute("aria-label", "Risk by departure hour for the day");
  const selHour = Number(depart.slice(11));
  const tideHours = res.high_tides.map(x => Number(x.slice(0, 2)) + (Number(x.slice(3)) >= 30 ? 1 : 0)).map(h => h % 24);
  res.strip.forEach(c => {
    const cell = el("div", "cell"); cell.dataset.level = c.level;
    if (c.hour === selHour) cell.classList.add("sel");
    if (tideHours.includes(c.hour)) cell.classList.add("tide");
    cell.title = pad(c.hour) + ":00 " + c.level + (c.rain !== null && c.rain !== undefined ? ", " + c.rain + " mm" : "");
    strip.append(cell);
  });
  box.append(strip);
  const ticks = el("div", "ticks"); [0,3,6,9,12,15,18,21].forEach(h => ticks.append(el("span", "", pad(h)))); box.append(ticks);
  const key = el("p", "key");
  [["k-low", "Lower risk"], ["k-mid", "Caution"], ["k-high", "High risk"], ["k-tide", "High tide"]].forEach(([c, t]) => { const s = el("span"); s.append(el("b", c), el("em", "", t)); key.append(s); });
  box.append(key);
  box.append(el("p", "legend", "Hover or long-press a bar for its hour and rain total."));

  if (res.data_note) box.append(el("div", "note", res.data_note));

  if (res.mode === "live"){
    box.append(el("h2", "", "Did this area flood?"));
    const nowMs = istNow(); const nowKey = ymd(0) + "T" + pad(nowMs.h);
    const past = depart <= nowKey;
    const fb = el("div", "fb");
    const yes = el("button", "", "Yes, it flooded"), no = el("button", "", "No, it was fine");
    yes.type = no.type = "button";
    yes.disabled = no.disabled = !past;
    yes.addEventListener("click", () => sendFeedback(true, fb)); no.addEventListener("click", () => sendFeedback(false, fb));
    fb.append(yes, no);
    box.append(fb);
    box.append(el("p", "hint", past ? "Saved without your name or location." : "This opens once the hour has passed. To try it now, pick an earlier hour today and check again."));
  }
  if (res.fetched_at) box.append(el("p", "hint", "Forecast fetched " + res.fetched_at + ". " + res.disclaimer));
  else box.append(el("p", "hint", res.disclaimer));
  $("result").replaceChildren(box);
}

async function sendFeedback(flooded, holder){
  if (!last) return;
  holder.querySelectorAll("button").forEach(b => b.disabled = true);
  try {
    await api("/feedback", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({corridor:last.corridor, depart:last.depart, level:last.level, flooded})});
    holder.replaceChildren(el("p", "hint", "Thanks. Saved."));
  } catch (e) { holder.replaceChildren(el("div", "err", e.message)); }
}

async function run(){
  const corridor = $("area").value, depart = $("day").value + "T" + $("hour").value;
  $("go").disabled = true; $("result").replaceChildren(el("p", "hint", "Checking..."));
  try {
    if (mode === "replay" && !replays.length) throw new Error("No replay events are loaded.");
    const extra = mode === "replay" ? "&replay=" + encodeURIComponent($("event").value) : "";
    const res = await api("/check?corridor=" + encodeURIComponent(corridor) + "&mode=" + mode + extra + "&depart=" + encodeURIComponent(depart));
    last = {corridor, depart, level: res.level};
    render(res, depart); setSky(res, depart);
  } catch (e) { showError(e.message); }
  $("go").disabled = false;
}

function setMode(m){
  mode = m;
  $("tab-live").setAttribute("aria-pressed", String(m === "live"));
  $("tab-replay").setAttribute("aria-pressed", String(m === "replay"));
  $("evwrap").classList.toggle("hidden", m !== "replay");
  buildDayHour(); $("result").replaceChildren(); last = null; resetSky();
}
$("event").addEventListener("change", () => { buildDayHour(); $("result").replaceChildren(); });
$("tab-live").addEventListener("click", () => setMode("live"));
$("tab-replay").addEventListener("click", () => setMode("replay"));
$("go").addEventListener("click", run);
$("credit").classList.toggle("hidden", !USE_PHOTOS);
buildDayHour();
loadAreas();
