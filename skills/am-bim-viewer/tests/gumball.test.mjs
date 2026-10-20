// Gumball: axis mapping (world Z up), snapping, cancel, undo, and the
// "element-transforms" hand-off JSON.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { core } from './load-core.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const DATA = JSON.parse(readFileSync(resolve(here, '../../../mods/am-bim-viewer/viewer/demo.json'), 'utf8'));
const MODEL = core.meshBounds(DATA.elements);
const byName = n => DATA.elements.find(e => e.name === n);
const VIEW = { height: 600 };
const O = { x: 400, y: 300 };

function view(name) {
  return core.setNamedView({ ...core.createViewState(), aspect: 1.5 }, name, MODEL);
}
const drag = (handle, s, dx, dy, isFree = true, pivot = O) => core.gumballDrag(handle, s, O, { x: O.x + dx, y: O.y + dy }, { ...VIEW, pivot }, isFree);

test('Top view: X arrow +100 px right moves east (+X); Y arrow +100 px up moves north (+Y)', () => {
  const s = view('top');
  const wpp = core.worldPerPixel(s, VIEW.height);
  const x = drag('x', s, 100, 0).move, y = drag('y', s, 0, -100).move;
  assert.ok(Math.abs(x[0] - 100 * wpp) < 1e-9 && x[1] === 0 && x[2] === 0, 'X: ' + x);
  assert.ok(Math.abs(y[1] - 100 * wpp) < 1e-9 && y[0] === 0 && y[2] === 0, 'Y: ' + y);
  assert.ok(Math.abs(drag('y', s, 100, 0).move[1]) < 1e-9, 'a sideways drag does not move along Y in Top');
  assert.ok(drag('x', s, -100, 0).move[0] < 0, 'left = west');
});

test('Front view: Z arrow up moves up (+Z), X arrow right moves east; Right view: drag right moves north', () => {
  const f = view('front');
  assert.ok(drag('z', f, 0, -100).move[2] > 0);
  assert.ok(drag('x', f, 100, 0).move[0] > 0);
  assert.ok(view('right') && drag('y', view('right'), 100, 0).move[1] > 0);
});

test('Perspective: dragging along the drawn axis direction moves +axis', () => {
  const s = view('perspective');
  const ax = core.gizmoAxes(s);
  for (const k of ['x', 'y', 'z']) {
    const [sx, sy] = ax[k];
    const m = drag(k, s, sx * 100, -sy * 100).move;
    assert.ok(m['xyz'.indexOf(k)] > 0, k + ' ' + m);
  }
});

test('Rotate ring: counterclockwise in plan is positive (Top view), as in Revit', () => {
  const s = view('top');
  const from = { x: O.x + 50, y: O.y }, up = { x: O.x, y: O.y - 50 }, down = { x: O.x, y: O.y + 50 };
  assert.equal(core.gumballDrag('rz', s, from, up, { ...VIEW, pivot: O }).rotateZ, 90);
  assert.equal(core.gumballDrag('rz', s, from, down, { ...VIEW, pivot: O }).rotateZ, -90);
  // Perspective looks from above too: same sense.
  assert.ok(core.gumballDrag('rz', view('perspective'), from, up, { ...VIEW, pivot: O }).rotateZ > 0);
  // A point rotated +90 about Z goes from east of the pivot to north of it.
  const rec = { move: [0, 0, 0], rotateZ: 90, pivot: [10, 10, 0] };
  const p = core.applyEditToPoint(rec, [11, 10, 5]);
  assert.ok(Math.abs(p[0] - 10) < 1e-9 && Math.abs(p[1] - 11) < 1e-9 && p[2] === 5, 'rotated point ' + p);
});

test('Snapping: moves snap to 1/2 ft and rotations to 5 deg unless Alt (free)', () => {
  const s = view('top');
  const wpp = core.worldPerPixel(s, VIEW.height);
  const px = 1.3 / wpp; // 1.3 ft of drag
  assert.equal(drag('x', s, px, 0, false).move[0], 1.5);
  assert.ok(Math.abs(drag('x', s, px, 0, true).move[0] - 1.3) < 1e-9);
  const from = { x: O.x + 50, y: O.y };
  const t = (17 * Math.PI) / 180, to = { x: O.x + 50 * Math.cos(t), y: O.y - 50 * Math.sin(t) };
  assert.equal(core.gumballDrag('rz', s, from, to, { ...VIEW, pivot: O }, false).rotateZ, 15);
  assert.ok(Math.abs(core.gumballDrag('rz', s, from, to, { ...VIEW, pivot: O }, true).rotateZ - 17) < 1e-9);
  assert.equal(core.gumballReadout('x', { move: [2.5, 0, 0] }), 'move x +2.50 ft');
  assert.equal(core.gumballReadout('y', { move: [0, -0.5, 0] }), 'move y -0.50 ft');
  assert.equal(core.gumballReadout('rz', { rotateZ: 15 }), 'rotate 15 deg');
});

test('Esc cancels a drag: a new record disappears, an existing one returns to its value', () => {
  const edits = core.createEdits();
  const col = byName('NE corner column');
  let d = core.beginGumballDrag(edits, col);
  d.update({ move: [2, 0, 0] });
  assert.deepEqual(core.pendingEdits(edits).map(r => r.move), [[2, 0, 0]]);
  d.cancel();
  assert.deepEqual(core.pendingEdits(edits), []);
  d = core.beginGumballDrag(edits, col); d.update({ move: [1, 0, 0] }); d.commit();
  d = core.beginGumballDrag(edits, col); d.update({ rotateZ: 30 }); d.update({ rotateZ: 45 });
  d.cancel();
  assert.deepEqual([edits.byId[String(col.id)].move, edits.byId[String(col.id)].rotateZ], [[1, 0, 0], 0]);
  d = core.beginGumballDrag(edits, byName('South wall') || DATA.elements[0]); d.commit();
  assert.equal(edits.order.length, 1, 'a drag that changed nothing leaves no record');
});

test('Undo one item and Clear all', () => {
  const edits = core.createEdits();
  const [a, b] = [DATA.elements[0], DATA.elements[1]];
  core.beginGumballDrag(edits, a).update({ move: [0, 1, 0] });
  core.beginGumballDrag(edits, b).update({ rotateZ: 10 });
  core.undoEdit(edits, a.id);
  assert.deepEqual(core.pendingEdits(edits).map(r => r.id), [b.id]);
  core.clearEdits(edits);
  assert.deepEqual(core.pendingEdits(edits), []);
  // Moving an element back to where it was leaves nothing to send to Revit.
  let d = core.beginGumballDrag(edits, a); d.update({ move: [1, 0, 0] }); d.commit();
  d = core.beginGumballDrag(edits, a); d.update({ move: [-1, 0, 0] }); d.commit();
  assert.deepEqual(core.exportTransforms(edits).items, []);
});

// Reference: what the viewer shows. A move translates; a rotation turns about the element's
// current center (where the gumball sits). Applied step by step to a real point of the element.
function simulate(steps, pivot, p) {
  let q = p.slice(), center = pivot.slice();
  for (const s of steps) {
    if (s.move) { q = q.map((v, i) => v + s.move[i]); center = center.map((v, i) => v + s.move[i]); }
    if (s.rotateZ) {
      const t = (s.rotateZ * Math.PI) / 180, dx = q[0] - center[0], dy = q[1] - center[1];
      q = [center[0] + Math.cos(t) * dx - Math.sin(t) * dy, center[1] + Math.sin(t) * dx + Math.cos(t) * dy, q[2]];
    }
  }
  return q.map(v => Math.round(v * 1e6) / 1e6);
}

test('Contract: rotate about the original pivot FIRST, then move, reproduces move-then-rotate and rotate-then-move', () => {
  const col = byName('NE corner column');
  const corner = col.mesh.vertices.slice(0, 3);
  for (const steps of [
    [{ move: [3, -1.5, 0] }, { rotateZ: 30 }],
    [{ rotateZ: 30 }, { move: [3, -1.5, 0] }],
    [{ move: [1, 0, 0.5] }, { rotateZ: 45 }, { move: [0, 2, 0] }, { rotateZ: -15 }],
  ]) {
    const edits = core.createEdits();
    for (const s of steps) { const d = core.beginGumballDrag(edits, col); d.update(s); d.commit(); }
    const [item] = core.exportTransforms(edits).items;
    // Apply the exported item exactly as am-safe-change does: rotate about pivot, then move.
    const t = (item.rotateZ * Math.PI) / 180, dx = corner[0] - item.pivot[0], dy = corner[1] - item.pivot[1];
    const applied = [item.pivot[0] + Math.cos(t) * dx - Math.sin(t) * dy + item.move[0], item.pivot[1] + Math.sin(t) * dx + Math.cos(t) * dy + item.move[1], corner[2] + item.move[2]];
    const b = core.elementBounds(col);
    assert.deepEqual(item.pivot, [0, 1, 2].map(i => (b.min[i] + b.max[i]) / 2), 'pivot is the original center, before the move');
    assert.deepEqual(applied.map(v => Math.round(v * 1e3) / 1e3), simulate(steps, item.pivot, corner).map(v => Math.round(v * 1e3) / 1e3), JSON.stringify(steps));
  }
});

test('Copy changes for Revit: the element-transforms JSON contract', () => {
  const edits = core.createEdits();
  const col = byName('NE corner column');
  const d = core.beginGumballDrag(edits, col);
  d.update({ move: [2.5, -0.5, 0] }); d.commit();
  const r = core.beginGumballDrag(edits, col); r.update({ rotateZ: 15 }); r.commit();
  const b = core.elementBounds(col);
  assert.deepEqual(core.exportTransforms(edits), {
    kind: 'element-transforms',
    source: 'am-bim-viewer',
    units: 'ft',
    items: [{
      id: col.id, name: 'NE corner column', category: col.category,
      move: [2.5, -0.5, 0], rotateZ: 15,
      pivot: [0, 1, 2].map(i => (b.min[i] + b.max[i]) / 2),
    }],
  });
  // The pivot (original center) lands at pivot + move: rotation keeps the center.
  const rec = edits.byId[String(col.id)];
  const c = core.applyEditToPoint(rec, rec.pivot);
  assert.deepEqual(c.map(v => Math.round(v * 1e9) / 1e9), rec.pivot.map((v, i) => v + rec.move[i]));
});
