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
  // Theme: dispatching am-theme-change with each theme recolors the scene (selection, outline, grid,
  // gizmo, categories) and the CSS backdrop. Restores the page's own theme afterwards.
  const html = document.documentElement, was = html.className;
  async function themed(theme) {
    html.classList.toggle('am-night', theme === 'night'); html.classList.toggle('am-paper', theme === 'paper');
    document.dispatchEvent(new CustomEvent('am-theme-change', { detail: { theme } })); await wait(60);
    return __bim.sceneColors();
  }
  const night = await themed('night'), paper = await themed('paper');
  html.className = was; document.dispatchEvent(new CustomEvent('am-theme-change', { detail: { theme: (window.amTheme && amTheme.get()) || 'paper' } })); await wait(60);
  results.themeNight = night.theme === 'night' && night.selected === '#f4f4f1' && night.outline === '#0a0a0a' && night.gizmo === '#9a9a96' && night.backdrop === 'rgb(10, 10, 10)';
  results.themePaper = paper.theme === 'paper' && paper.selected === '#0a0a0a' && paper.outline === '#f4f4f1' && paper.gizmo === '#6b6b68' && paper.backdrop === 'rgb(244, 244, 241)';
  results.themeRecolorsGrid = night.grid !== paper.grid;
  results.categoriesAreGray = Object.values(night.categories).every(h => { const c = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)); return Math.max(...c) - Math.min(...c) <= 6; });
  // Clean viewport: flat --bg, no image behind the model, and the page grain (z 50) stays below it.
  const vs = getComputedStyle(document.getElementById('viewport'));
  const grainZ = Number(getComputedStyle(document.body, '::after').zIndex);
  results.viewportFlat = vs.backgroundImage === 'none' && getComputedStyle(c).backgroundImage === 'none' && Number(vs.zIndex) > grainZ;
  // Axis gizmo: small and quiet, at most 48 px.
  const gz = document.getElementById('gizmo').getBoundingClientRect();
  results.gizmoSmall = gz.width > 0 && gz.width <= 48 && gz.height <= 48;
  // Grid at a grazing angle: the far band dissolves into the clean field (low pixel variance);
  // negative control with the density fade off must alias into texture (high variance).
  async function farBandVariance(fade) {
    __bim.gridOnly(true); __bim.gridDensityFade(fade);
    const s = __bim.state, b = __bim.bounds;
    s.projection = 'perspective'; s.elevation = 3 * Math.PI / 180;
    s.target = [(b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, b.min[2]];
    s.distance = Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1]) * 0.6;
    __bim.renderNow(); await wait(30);
    const w = c.width, h = c.height, cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    const g = cv.getContext('2d'); g.fillStyle = getComputedStyle(document.getElementById('viewport')).backgroundColor; g.fillRect(0, 0, w, h); g.drawImage(c, 0, 0);
    const horizon = h / 2 - (Math.tan(s.elevation) / Math.tan((s.fov * Math.PI) / 360)) * (h / 2);
    const y0 = Math.round(horizon + h * 0.005), y1 = Math.round(horizon + h * 0.08);
    const px = g.getImageData(Math.round(w * 0.1), y0, Math.round(w * 0.8), y1 - y0).data;
    // High-frequency energy: mean absolute luminance step between neighbouring pixels (texture, not lines).
    const bw = Math.round(w * 0.8), bh = y1 - y0, L = i => px[i] * .2126 + px[i + 1] * .7152 + px[i + 2] * .0722;
    let n = 0, e = 0;
    for (let y = 0; y < bh - 1; y++) for (let x = 0; x < bw - 1; x++) { const i = (y * bw + x) * 4; e += Math.abs(L(i) - L(i + 4)) + Math.abs(L(i) - L(i + bw * 4)); n++; }
    return e / n;
  }
  const varOn = await farBandVariance(true), varOff = await farBandVariance(false);
  __bim.gridDensityFade(true); __bim.gridOnly(false); __bim.setView('perspective'); await wait(30);
  results.gridNoMoire = varOn < 4.5 && varOff > 4.5 && varOff / varOn > 2; // measured: on 3.0, off 7.3 (night demo)
  results.gridVariance = { on: Math.round(varOn * 10) / 10, off: Math.round(varOff * 10) / 10, isInfo: true };
  // Cursors: the soft shadow (paper) or halo (night) really renders outside the outline.
  // Render each cursor SVG into an <img> at 1x and 3x; count pixels that are empty without the
  // filter but painted with it. Negative control: the same count on the unfiltered render is 0.
  async function haloPixels(name, theme, scale, isFiltered) {
    const svgOf = f => __bim.cursor.svg(name, theme, { filter: f });
    const load = src => new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = 'data:image/svg+xml,' + encodeURIComponent(src); });
    const draw = async src => { const cv = document.createElement('canvas'); cv.width = cv.height = 32 * scale; const g = cv.getContext('2d'); g.drawImage(await load(src), 0, 0, cv.width, cv.height); return g.getImageData(0, 0, cv.width, cv.height).data; };
    const bare = await draw(svgOf(false)), test = await draw(svgOf(isFiltered));
    let shape = 0, halo = 0;
    for (let i = 3; i < bare.length; i += 4) { if (bare[i] > 0) shape++; else if (test[i] > 6) halo++; }
    return { shape, halo };
  }
  const cursorRows = [];
  for (const name of __bim.cursor.names) for (const theme of ['paper', 'night']) for (const scale of [1, 3]) {
    const on = await haloPixels(name, theme, scale, true), off = await haloPixels(name, theme, scale, false);
    cursorRows.push(on.shape > 0 && on.halo >= 8 * scale && off.halo === 0);
  }
  results.cursorShadowRenders = cursorRows.length === 20 && cursorRows.every(Boolean);
  // Help: the pointer is simulated with real hit-testing (document.elementFromPoint) so the test
  // measures hit areas, not which element we chose to dispatch on. pointerenter/leave are sent
  // along the ancestor chains exactly as a browser does when the element under the pointer changes.
  const help = document.getElementById('help'), hb = document.getElementById('helpbtn'), hp = document.getElementById('helppanel');
  const isOpen = () => getComputedStyle(hp).visibility === 'visible' && hb.getAttribute('aria-expanded') === 'true';
  // Closed = collapsed state and no hit area (immediate); visibility fades out over --slow.
  const isClosed = () => getComputedStyle(hp).pointerEvents === 'none' && hb.getAttribute('aria-expanded') === 'false' && !help.classList.contains('open');
  let under = null;
  const chain = el => { const out = []; for (let n = el; n; n = n.parentElement) out.push(n); return out; };
  function pointerTo(x, y, buttons = 0) {
    const el = document.elementFromPoint(x, y);
    if (el === under) return el;
    const oldC = chain(under), newC = chain(el);
    const opts = { pointerId: 9, pointerType: 'mouse', clientX: x, clientY: y, buttons };
    for (const n of oldC) if (!newC.includes(n)) n.dispatchEvent(new PointerEvent('pointerleave', opts));
    for (const n of newC.slice().reverse()) if (!oldC.includes(n)) n.dispatchEvent(new PointerEvent('pointerenter', opts));
    under = el; return el;
  }
  const hbR = hb.getBoundingClientRect(), hbC = { x: hbR.left + hbR.width / 2, y: hbR.top + hbR.height / 2 };
  const vpR = document.getElementById('viewport').getBoundingClientRect();
  const away = { x: vpR.left + 60, y: vpR.top + 80 }; // far from the ? and from the open panel
  pointerTo(away.x, away.y); await wait(300);
  const rest = isClosed();
  pointerTo(hbR.left - 8, hbC.y); await wait(250);                      // 8 px outside the "?"
  const outside8 = isClosed();
  pointerTo(hbC.x, hbC.y); await wait(80); pointerTo(away.x, away.y); await wait(250); // < 150 ms then leave
  const brief = isClosed();
  pointerTo(hbC.x, hbC.y); await wait(220);                              // > 150 ms
  const opened = isOpen() && hp.querySelectorAll('kbd').length >= 9;
  const pR = hp.getBoundingClientRect();
  pointerTo(hbC.x, hbR.top - 4); await wait(60);                         // the gap between ? and panel
  pointerTo(pR.left + pR.width / 2, pR.top + pR.height / 2); await wait(350);
  const keptOverPanel = isOpen();
  pointerTo(away.x, away.y); await wait(400);                            // leave both
  const closedAfterLeave = isClosed();
  pointerTo(hbC.x, hbC.y, 2); await wait(250);                           // right-button drag passing over
  const dragIgnored = isClosed();
  pointerTo(away.x, away.y); await wait(300);
  // Without OS focus (an automated pane), focus() moves activeElement but fires no focus events: send focusin.
  hb.focus(); if (!document.hasFocus()) hb.dispatchEvent(new FocusEvent('focusin', { bubbles: true })); await wait(20);
  const focused = isOpen();
  hb.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await wait(450);
  const escaped = isClosed() && hb.getAttribute('aria-controls') === 'helppanel';
  results.helpHover = { rest, outside8, brief, opened, keptOverPanel, closedAfterLeave, dragIgnored, focused, escaped, isInfo: true };
  results.helpCollapses = rest && outside8 && brief && opened && keptOverPanel && closedAfterLeave && dragIgnored && focused && escaped;
  // Gumball (left drag on a handle): Top view, X arrow +100 px moves east, Y arrow up moves north,
  // ring CCW is positive; snapping; Esc cancels; undo; Copy for Revit gives the contract JSON.
  __bim.setView('top'); __bim.select(310009); __bim.renderNow(); await wait(30);
  const gum = document.getElementById('gumball');
  function gdragTo(handle, dx, dy, opts = {}) {
    const L = __bim.gumball.layout();
    const from = handle === 'rz' ? L.ringEast : L.tips[handle];
    const target = gum.querySelector('.h[data-h="' + handle + '"] .hit');
    const ev = (t, X, Y) => new PointerEvent(t, { bubbles: true, cancelable: true, pointerId: 7, pointerType: 'mouse', button: 0, buttons: t === 'pointerup' ? 0 : 1, clientX: X, clientY: Y, altKey: !!opts.alt });
    target.dispatchEvent(ev('pointerdown', from.x, from.y));
    const to = typeof dx === 'function' ? dx(from, L.center) : { x: from.x + dx, y: from.y + dy };
    gum.dispatchEvent(ev('pointermove', to.x, to.y));
    if (opts.cancel) window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    else gum.dispatchEvent(ev('pointerup', to.x, to.y));
  }
  const items = () => __bim.gumball.transforms().items;
  gdragTo('x', 100, 0); __bim.renderNow();
  const afterX = items()[0];
  results.gumballXEast = !!afterX && afterX.move[0] > 0 && afterX.move[1] === 0 && afterX.move[2] === 0 && afterX.move[0] % 0.5 === 0;
  gdragTo('y', 0, -100);
  const afterY = items()[0];
  results.gumballYNorth = afterY.move[1] > 0 && afterY.move[0] === afterX.move[0];
  gdragTo('rz', (from, c) => ({ x: c.x, y: c.y - (from.x - c.x) }));
  results.gumballRingCCW = items()[0].rotateZ === 90;
  results.gumballGhostAndPending = __bim.gumball.ghostCount() === 1 && __bim.gumball.pendingRows() === 1;
  const keep = JSON.stringify(items());
  gdragTo('x', 137, 0, { cancel: true });
  results.gumballEscCancels = JSON.stringify(items()) === keep && !__bim.gumball.isDragging();
  gdragTo('x', 37, 0, { alt: true }); // free: not a multiple of 1/2 ft
  results.gumballAltFree = items()[0].move[0] % 0.5 !== 0;
  document.getElementById('copyrevit').click(); await wait(30);
  const copied = JSON.parse(__bim.gumball.lastCopied());
  results.gumballCopyContract = copied.kind === 'element-transforms' && copied.source === 'am-bim-viewer' && copied.units === 'ft' &&
    copied.items.length === 1 && Object.keys(copied.items[0]).join() === 'id,name,category,move,rotateZ,pivot' && copied.items[0].id === 310009;
  document.querySelector('#pending [data-undo]').click(); await wait(30);
  results.gumballUndo = items().length === 0 && __bim.gumball.ghostCount() === 0 && __bim.gumball.meshMatrix(310009).every((v, i) => v === [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1][i]);
  __bim.select(null); __bim.setView('perspective');
  results.noFooter =!document.querySelector('footer');
  results.oneViewLabel = document.querySelectorAll('#viewname *').length === 0 && document.getElementById('viewname').textContent !== '';
  return { pass: Object.entries(results).every(([k, v]) => v && (v === true || v.isInfo)), results };
})();
