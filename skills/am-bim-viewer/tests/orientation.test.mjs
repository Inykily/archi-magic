// Orientation proof: project known world points (Revit coords, Z up) through
// the real three.js cameras that the viewer builds, and check where they land.
// NDC: x to the right, y up, both -1..1.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const BOUNDS = { min: [0, 0, -1], max: [60, 50, 24] }; // demo L-building
const C = [30, 25, 11.5]; // its center

function camFor(view) {
  const state = core.setNamedView(core.createViewState(), view, BOUNDS);
  const cams = { persp: new THREE.PerspectiveCamera(), ortho: new THREE.OrthographicCamera() };
  return { state, cam: core.applyView(THREE, state, cams, 1.5) };
}
function ndc(cam, p) {
  return new THREE.Vector3(p[0], p[1], p[2]).project(cam);
}
const off = (d) => [C[0] + d[0], C[1] + d[1], C[2] + d[2]];
const EPS = 1e-6;

// Handedness: world axes expressed in camera space must form a right-handed
// set (det = +1). A mirror (negative scale, swapped axes) gives det = -1.
function viewDet(cam) {
  const m = new THREE.Matrix3().setFromMatrix4(cam.matrixWorldInverse);
  return m.determinant();
}
// Screen-space chirality of two world axes a, b: z of (screen a) x (screen b).
function screenCross(cam, a, b) {
  const o = ndc(cam, C), pa = ndc(cam, off(a)), pb = ndc(cam, off(b));
  return (pa.x - o.x) * (pb.y - o.y) - (pa.y - o.y) * (pb.x - o.x);
}

test('Top view: plan looks down -Z, North (+Y) up, East (+X) right, not mirrored', () => {
  const { cam } = camFor('top');
  assert.equal(cam.isOrthographicCamera, true);
  const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
  assert.ok(dir.z < -0.999999, 'camera looks along -Z, got ' + dir.toArray());
  const n = ndc(cam, off([0, 10, 0])), e = ndc(cam, off([10, 0, 0]));
  assert.ok(n.y > 0.05 && Math.abs(n.x) < EPS, 'North point above center: ' + n.toArray());
  assert.ok(e.x > 0.05 && Math.abs(e.y) < EPS, 'East point right of center: ' + e.toArray());
  assert.ok(screenCross(cam, [1, 0, 0], [0, 1, 0]) > 0, 'X then Y turns counter-clockwise on screen (seen from +Z)');
});

test('Front view: looks from -Y toward +Y, Z up, +X right', () => {
  const { cam } = camFor('front');
  const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
  assert.ok(dir.y > 0.999999, 'camera looks along +Y, got ' + dir.toArray());
  const up = ndc(cam, off([0, 0, 10])), e = ndc(cam, off([10, 0, 0])), n = ndc(cam, off([0, 10, 0]));
  assert.ok(up.y > 0.05 && Math.abs(up.x) < EPS, 'Z-up point above center');
  assert.ok(e.x > 0.05 && Math.abs(e.y) < EPS, '+X to the right');
  assert.ok(Math.abs(n.x) < EPS && Math.abs(n.y) < EPS, '+Y goes straight away from the viewer');
  assert.ok(screenCross(cam, [1, 0, 0], [0, 0, 1]) > 0, 'X then Z counter-clockwise (seen from -Y)');
});

test('Right view: looks from +X toward -X, +Y right, Z up', () => {
  const { cam } = camFor('right');
  const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
  assert.ok(dir.x < -0.999999, 'camera looks along -X, got ' + dir.toArray());
  const n = ndc(cam, off([0, 10, 0])), up = ndc(cam, off([0, 0, 10]));
  assert.ok(n.x > 0.05 && Math.abs(n.y) < EPS, '+Y to the right');
  assert.ok(up.y > 0.05 && Math.abs(up.x) < EPS, 'Z up');
});

test('Perspective (SE iso): camera at +X -Y +Z, Z up, North-East corner behind', () => {
  const { cam } = camFor('perspective');
  assert.equal(cam.isPerspectiveCamera, true);
  const pos = cam.position.clone().sub(new THREE.Vector3(...C));
  assert.ok(pos.x > 0 && pos.y < 0 && pos.z > 0, 'camera is south-east and above: ' + pos.toArray());
  const up = ndc(cam, off([0, 0, 10]));
  assert.ok(up.y > 0.05 && Math.abs(up.x) < 1e-3, 'vertical stays vertical on screen');
  const e = ndc(cam, off([10, 0, 0])), n = ndc(cam, off([0, 10, 0]));
  assert.ok(e.x > 0 && n.x > 0, 'from the SE, both East and North go to the right');
  assert.ok(n.y > e.y, 'North (farther) projects higher than East');
});

test('Handedness is preserved in every view (det = +1, no mirror)', () => {
  for (const view of ['top', 'front', 'right', 'perspective']) {
    const { cam } = camFor(view);
    assert.ok(Math.abs(viewDet(cam) - 1) < 1e-9, view + ': det ' + viewDet(cam));
  }
});

test('Orbit keeps the horizon level (no roll) and Z up', () => {
  const { state } = camFor('perspective');
  const cams = { persp: new THREE.PerspectiveCamera(), ortho: new THREE.OrthographicCamera() };
  for (const [dx, dy] of [[120, 0], [-300, 40], [37, -90], [500, 500]]) {
    core.orbit(state, dx, dy);
    const cam = core.applyView(THREE, state, cams, 1.5);
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(cam.quaternion);
    assert.ok(Math.abs(right.z) < 1e-12, 'screen-right stays horizontal, z=' + right.z);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
    assert.ok(up.z >= -1e-12, 'screen-up never points below the horizon');
    assert.ok(Math.abs(viewDet(cam) - 1) < 1e-9, 'still right-handed');
  }
});

test('Chiral demo footprint is not mirrored in Top view', () => {
  // The east wing (x 40..60) runs north. In Top view its tip must be upper-right.
  const { cam } = camFor('top');
  const tip = ndc(cam, [50, 48, 0]), sw = ndc(cam, [2, 2, 0]);
  assert.ok(tip.x > sw.x && tip.y > sw.y, 'NE wing tip is right of and above the SW corner');
});
