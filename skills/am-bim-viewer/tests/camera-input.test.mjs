// Camera mapping: which mouse button + modifier does what (Rhino defaults),
// and what each action does to the view.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const L = 0, M = 1, R = 2;

test('mapPointer follows the Rhino mouse table (perspective and parallel)', () => {
  const rows = [];
  for (const isParallel of [false, true]) {
    for (const [button, shift, ctrl] of [[R, false, false], [R, true, false], [R, false, true], [R, true, true], [L, false, false], [L, true, true], [M, false, false]]) {
      rows.push([isParallel ? 'parallel' : 'perspective', button, shift, ctrl, core.mapPointer({ button, shift, ctrl, isParallel })]);
    }
  }
  assert.deepEqual(rows, [
    ['perspective', R, false, false, 'rotate'],
    ['perspective', R, true, false, 'pan'],
    ['perspective', R, false, true, 'zoom'],
    ['perspective', R, true, true, 'rotate'],
    ['perspective', L, false, false, 'select'],
    ['perspective', L, true, true, 'select'],
    ['perspective', M, false, false, 'pan'],
    ['parallel', R, false, false, 'pan'],
    ['parallel', R, true, false, 'pan'],
    ['parallel', R, false, true, 'zoom'],
    ['parallel', R, true, true, 'rotate'],
    ['parallel', L, false, false, 'select'],
    ['parallel', L, true, true, 'select'],
    ['parallel', M, false, false, 'pan'],
  ]);
  assert.deepEqual([core.mapWheel({ ctrl: false }), core.mapWheel({ ctrl: true })], ['zoom-cursor', 'zoom-center']);
});

function setup(view = 'perspective') {
  const state = core.setNamedView(core.createViewState(), view, { min: [0, 0, 0], max: [60, 50, 24] });
  const cams = { persp: new THREE.PerspectiveCamera(), ortho: new THREE.OrthographicCamera() };
  const project = p => new THREE.Vector3(...p).project(core.applyView(THREE, state, cams, 1.5));
  return { state, project };
}

test('Rotate: dragging right moves the near face of the model to the right', () => {
  const { state, project } = setup('perspective');
  // Near point: from the target toward the camera, on the ground plane.
  const pos = core.cameraPosition(state);
  const near = [state.target[0] + (pos[0] - state.target[0]) * 0.3, state.target[1] + (pos[1] - state.target[1]) * 0.3, state.target[2]];
  const before = project(near).x;
  core.orbit(state, 40, 0);
  assert.ok(project(near).x > before + 0.01, 'near point moved right');
});

test('Rotate: dragging up tilts the camera down (near face follows the cursor up)', () => {
  const { state } = setup('perspective');
  const e0 = state.elevation;
  core.orbit(state, 0, -30); // up = negative dy in screen pixels
  assert.ok(state.elevation < e0);
});

test('Pan: the point under the cursor follows the cursor', () => {
  const { state, project } = setup('top');
  const H = 800; // viewport height in px
  const p = [30, 25, 0];
  const a = project(p);
  core.pan(state, 100, 0, H);
  const b = project(p);
  // 100 px right on an 800 px high viewport = 0.25 NDC units horizontally at aspect 1.5 ... in px:
  const dxPx = ((b.x - a.x) / 2) * (H * 1.5);
  assert.ok(Math.abs(dxPx - 100) < 1e-6, 'moved ' + dxPx + ' px');
  assert.ok(Math.abs(b.y - a.y) < 1e-9);
});

test('Zoom: Ctrl+right drag up zooms in, down zooms out', () => {
  assert.ok(core.dragZoomFactor(-20) < 1);
  assert.ok(core.dragZoomFactor(20) > 1);
});

test('Wheel zoom at cursor keeps the point under the cursor fixed', () => {
  for (const view of ['top', 'perspective']) {
    const { state, project } = setup(view);
    const ndcX = 0.4, ndcY = -0.3, aspect = 1.5;
    const { r, u } = core.cameraBasis(state.azimuth, state.elevation);
    const hh = core.halfHeight(state);
    const p = [0, 1, 2].map(i => state.target[i] + r[i] * ndcX * hh * aspect + u[i] * ndcY * hh);
    const a = project(p);
    core.zoomAt(state, 0.5, ndcX, ndcY, aspect);
    const b = project(p);
    assert.ok(Math.abs(a.x - ndcX) < 1e-9 && Math.abs(a.y - ndcY) < 1e-9, view + ': point starts under the cursor');
    assert.ok(Math.abs(b.x - a.x) < 1e-9 && Math.abs(b.y - a.y) < 1e-9, view + ': point stays under the cursor');
  }
});

test('Units: lengths show feet and metres', () => {
  assert.equal(core.formatParam({ v: 12, u: 'ft' }), '12.00 ft (3.658 m)');
  assert.equal(core.formatParam('D1'), 'D1');
});
