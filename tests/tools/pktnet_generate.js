// Run a PKTNET form page's own "Generate" handler and print the text it
// writes into its dialog's textarea. Test-only (tests/unit/test_pktnet_forms.py):
// it proves a kissterm form data file writes what the page writes.
//
// usage: node pktnet_generate.js page.html values.json
// values.json: {"field_id": "text", "checkbox_id": true, ...}
//
// jQuery is a stub: $("#id") is a field holding values[id]; anything the
// handler builds with $("<...>") is captured. document.ready runs first
// (it sets the date/time defaults), then the values are applied, then the
// #generate click handler runs.
const fs = require("fs");
const [page, valuesPath] = process.argv.slice(2);
const html = fs.readFileSync(page, "utf8");
const values = JSON.parse(fs.readFileSync(valuesPath, "utf8"));
const store = {};
// A <span id> label's text, as the page has it (Severe WX's units).
for (const m of html.matchAll(/<span id="([\w-]+)">([^<]*)<\/span>/g)) store[m[1]] = m[2];
const handlers = {};
let captured = null;
let ready = [];

function field(id) {
  const el = {
    val(v) { if (v === undefined) return store[id] === undefined ? "" : String(store[id]); store[id] = v; return el; },
    prop(name, v) { if (name === "checked") { if (v === undefined) return store[id] === true; store[id] = v; } return el; },
    attr() { return undefined; },
    css() { return el; },
    on(evt, fn) { handlers[id + ":" + evt] = fn; return el; },
    empty() { return el; }, dialog() { return el; }, trigger() { return el; },
    appendTo() { return el; }, append() { return el; }, click() { return el; },
    each() { return el; }, remove() { return el; },
    text(v) { if (v === undefined) return store[id] === undefined ? "" : String(store[id]); store[id] = v; return el; },
    is() { return false; }, find() { return el; }, length: 1,
  };
  return el;
}
function $(arg) {
  if (typeof arg === "function") { ready.push(arg); return field("_"); }
  if (arg === document) { const d = field("_document"); d.ready = (fn) => { ready.push(fn); return d; }; return d; }
  if (typeof arg === "string" && arg.trim().startsWith("<")) { captured = arg; return field("_built"); }
  if (typeof arg === "string" && /^#[\w-]+$/.test(arg)) return field(arg.slice(1));
  const none = field("_none"); none.length = 0; return none;
}
const document = {};
const window = {};
const navigator = { clipboard: { writeText() {} } };
function prompt() { return null; }
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
for (const code of scripts) eval(code);
for (const fn of ready) fn();
for (const [k, v] of Object.entries(values)) store[k] = v;
handlers["generate:click"]();
const m = captured && captured.match(/<textarea[^>]*>([\s\S]*?)<\/textarea>/);
let text = m ? m[1] : "";
text = text.replace(/&nbsp;/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
process.stdout.write(text);
