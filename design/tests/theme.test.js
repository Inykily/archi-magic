const fs = require('fs'); const assert = require('assert');
const src = fs.readFileSync(process.argv[2] || require('path').join(__dirname, '..', 'theme.js'), 'utf8');
function makeEnv(nowIso, stored) {
  const classes = new Set(); const attrs = {}; const events = []; const store = Object.assign({}, stored || {});
  const RealDate = Date; const fixed = new RealDate(nowIso).getTime();
  class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } }
  const env = {
    Date: FakeDate, JSON, setInterval: () => 0,
    localStorage: { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } },
    document: { documentElement: { classList: { toggle: (c, on) => on ? classes.add(c) : classes.delete(c), contains: c => classes.has(c) }, setAttribute: (k, v) => { attrs[k] = v; } },
                dispatchEvent: e => events.push(e.detail.theme) },
    CustomEvent: function (n, o) { this.detail = o.detail; }, window: {}
  };
  new Function(...Object.keys(env), src)(...Object.values(env));
  return { classes, attrs, events, store, api: env.window.amTheme };
}
const t = s => makeEnv(s).attrs['data-am-theme'];
assert.strictEqual(t('2026-10-20T06:59:00'), 'night'); assert.strictEqual(t('2026-10-20T07:00:00'), 'paper');
assert.strictEqual(t('2026-10-20T18:59:00'), 'paper'); assert.strictEqual(t('2026-10-20T19:00:00'), 'night');
assert.strictEqual(t('2026-10-20T00:30:00'), 'night');
const e = makeEnv('2026-10-20T10:00:00');
assert.ok(e.classes.has('am-paper') && !e.classes.has('am-night')); assert.deepStrictEqual(e.events, ['paper']);
const nb = d => new Date(e.api._nextBoundary(new Date(d))).toString().slice(16, 21) + ' ' + new Date(e.api._nextBoundary(new Date(d))).getDate();
assert.strictEqual(nb('2026-10-20T10:00:00'), '19:00 20'); assert.strictEqual(nb('2026-10-20T21:00:00'), '07:00 21'); assert.strictEqual(nb('2026-10-20T05:00:00'), '07:00 20');
e.api.set('night'); assert.strictEqual(e.api.get(), 'night'); assert.ok(JSON.parse(e.store['am-theme-override']).theme === 'night');
// override still valid at 18:00 the same day, expired at 19:30 (past the boundary)
const ov = { 'am-theme-override': JSON.stringify({ theme: 'night', until: new Date('2026-10-20T19:00:00').getTime() }) };
assert.strictEqual(makeEnv('2026-10-20T18:00:00', ov).attrs['data-am-theme'], 'night');
const late = makeEnv('2026-10-20T19:30:00', ov); assert.strictEqual(late.attrs['data-am-theme'], 'night'); assert.ok(!('am-theme-override' in late.store), 'expired override removed');
const late2 = makeEnv('2026-10-21T08:00:00', ov); assert.strictEqual(late2.attrs['data-am-theme'], 'paper');
e.api.set('auto'); assert.ok(!('am-theme-override' in e.store)); assert.strictEqual(e.api.get(), 'paper');
// storage blocked: a manual switch must still change the theme AND send am-theme-change
(function () {
  const src2 = src;
  const classes = new Set(); const attrs = {}; const events = [];
  const RealDate = Date; const fixed = new RealDate('2026-10-20T10:00:00').getTime();
  class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } }
  const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  const env = { Date: FakeDate, JSON, setInterval: () => 0, localStorage: throwing,
    document: { documentElement: { classList: { toggle: (c, on) => on ? classes.add(c) : classes.delete(c) }, setAttribute: (k, v) => { attrs[k] = v; } }, dispatchEvent: e => events.push(e.detail.theme) },
    CustomEvent: function (n, o) { this.detail = o.detail; }, window: {} };
  new Function(...Object.keys(env), src2)(...Object.values(env));
  assert.deepStrictEqual(events, ['paper']);
  env.window.amTheme.set('night');
  assert.strictEqual(attrs['data-am-theme'], 'night'); assert.ok(classes.has('am-night'));
  assert.deepStrictEqual(events, ['paper', 'night'], 'blocked storage must still send am-theme-change');
  env.window.amTheme.set('auto'); assert.deepStrictEqual(events, ['paper', 'night', 'paper']);
})();
console.log('theme.js: all assertions passed');
