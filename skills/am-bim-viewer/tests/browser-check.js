// In-browser check for the built demo page (demo.viewer.html). Run it in the
// page (Claude Browser pane javascript tool, or the dev tools console). It
// drives the page's real pointer handlers and returns { pass, results }.
(async () => {
  const c = document.querySelector('#viewport canvas');
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const r = c.getBoundingClientRect();
  function click(x, y, isDouble) {
    const ev = (t, extra = {}) => new PointerEvent(t, { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 1, clientX: x, clientY: y, ...extra });
    const once = () => { c.dispatchEvent(ev('pointerdown')); c.dispatchEvent(ev('pointerup', { buttons: 0 })); };
    once();
    if (isDouble) { once(); c.dispatchEvent(new MouseEvent('dblclick', { bubbles: true, button: 0, clientX: x, clientY: y })); }
  }
  function rdrag(mods, dx, dy) {
    const x = r.left + r.width / 2, y = r.top + r.height / 2;
    const ev = (t, X, Y) => new PointerEvent(t, { bubbles: true, pointerId: 1, pointerType: 'mouse', button: 2, buttons: 2, clientX: X, clientY: Y, ...mods });
    c.dispatchEvent(ev('pointerdown', x, y)); c.dispatchEvent(ev('pointermove', x + dx, y + dy)); c.dispatchEvent(ev('pointerup', x + dx, y + dy));
  }
  const near = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < 1e-6);
  const results = {};
  __bim.setView('top'); await wait(50);
  let p = __bim.project(60, 50, 24); click(p.x, p.y); await wait(30);
  results.clickSelectsColumn = __bim.selectedId() === 310009 && document.querySelector('.sel-name').textContent === 'NE corner column';
  p = __bim.project(20, 10, 0); click(p.x, p.y); await wait(30);
  results.clickSelectsSlab = __bim.selectedId() === 310000;
  click(r.left + 4, r.bottom - 4); await wait(30);
  results.clickEmptyClears = __bim.selectedId() === null;
  let s0 = JSON.stringify(__bim.state.target); rdrag({}, 40, 0);
  results.parallelRightDragPans = JSON.stringify(__bim.state.target) !== s0;
  __bim.setView('perspective'); await wait(50);
  const az = __bim.state.azimuth; rdrag({}, 40, 0);
  results.perspRightDragRotates = __bim.state.azimuth < az;
  __bim.setView('perspective'); await wait(50);
  p = __bim.project(60, 50, 12); const before = __bim.panelRenders();
  click(p.x, p.y, true); await wait(450);
  results.dblClickSelectsOnce = __bim.selectedId() === 310009 && __bim.panelRenders() - before === 1;
  results.dblClickTargetsCenter = near(__bim.state.target, [60, 50, 12]);
  const corners = [];
  for (const x of [59, 61]) for (const y of [49, 51]) for (const z of [0, 24]) corners.push(__bim.project(x, y, z));
  results.dblClickFitsBox = corners.every(q => q.x >= r.left && q.x <= r.right && q.y >= r.top && q.y <= r.bottom);
  click(r.left + 4, r.top + 4, true); await wait(450);
  const after = { t: __bim.state.target.slice(), d: __bim.state.distance };
  __bim.setView('perspective');
  results.dblClickEmptyZoomsExtents = near(after.t, __bim.state.target) && Math.abs(after.d - __bim.state.distance) < 1e-6;
  const chip = document.querySelector('.chip[data-cat="Walls"]');
  const wallsVisible = () => __bim.visibleCount('Walls');
  const on0 = chip.getAttribute('aria-pressed') === 'true' && wallsVisible() === 6;
  chip.click(); await wait(30);
  const off = chip.getAttribute('aria-pressed') === 'false' && wallsVisible() === 0;
  chip.click(); await wait(30);
  results.wallsChipMatchesVisibility = on0 && off && chip.getAttribute('aria-pressed') === 'true' && wallsVisible() === 6;
  const cm = new MouseEvent('contextmenu', { bubbles: true, cancelable: true }); c.dispatchEvent(cm);
  results.contextMenuBlocked = cm.defaultPrevented;
  results.oneViewLabel = document.querySelectorAll('#viewname *').length === 0 && document.getElementById('viewname').textContent !== '';
  return { pass: Object.values(results).every(Boolean), results };
})();
