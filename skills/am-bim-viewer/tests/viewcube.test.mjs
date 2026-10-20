// View cube: face / edge / corner -> camera, Revit conventions (Z up, Y = north), checked on the
// real three.js cameras the page uses. "dir" below is the camera VIEW direction (-d in core terms).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const BOUNDS = { min: [0, 0, -1], max: [60, 50, 24] };
const C = [30, 25, 11.5];
const r6 = a => a.map(v => Math.round(v * 1e6) / 1e6 + 0);

function camForRegion(names, projection = 'perspective') {
  const v = core.cubeView(names);
  const state = { ...core.createViewState(), azimuth: v.azimuth, elevation: v.elevation, projection: v.projection || projection };
  core.setScene(state, BOUNDS); core.fitBounds(state, BOUNDS);
  const cams = { persp: new THREE.PerspectiveCamera(), ortho: new THREE.OrthographicCamera() };
  const cam = core.applyView(THREE, state, cams, 1.5);
  cam.updateMatrixWorld(true);
  const dir = new THREE.Vector3(); cam.getWorldDirection(dir);
  const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cam.quaternion);
  return { state, cam, dir: r6(dir.toArray()), up: r6(up.toArray()), isOrtho: cam.isOrthographicCamera === true };
}

test('Faces: view direction and up vector for all six (deep equality within 1e-6)', () => {
  const expected = {
    front: { dir: [0, 1, 0], up: [0, 0, 1] },   // camera south, looking north
    back: { dir: [0, -1, 0], up: [0, 0, 1] },   // camera north, looking south
    right: { dir: [-1, 0, 0], up: [0, 0, 1] },  // camera east, looking west
    left: { dir: [1, 0, 0], up: [0, 0, 1] },    // camera west, looking east
    top: { dir: [0, 0, -1], up: [0, 1, 0] },    // looking down, north up
    bottom: { dir: [0, 0, 1], up: [0, 1, 0] },  // looking up, north up
  };
  const got = {};
  for (const f of Object.keys(expected)) { const c = camForRegion([f]); got[f] = { dir: c.dir, up: c.up }; assert.ok(c.isOrtho, f + ' is a parallel view'); }
  assert.deepEqual(got, expected);
});

test('BOTTOM keeps north up, so east is on the screen left', () => {
  const { cam } = camForRegion(['bottom']);
  const o = new THREE.Vector3(...C).project(cam), e = new THREE.Vector3(C[0] + 10, C[1], C[2]).project(cam), n = new THREE.Vector3(C[0], C[1] + 10, C[2]).project(cam);
  assert.ok(e.x < o.x - 0.05 && n.y > o.y + 0.05);
});

test('Edge and corner: front-right edge is the 45 deg elevation view; top-front-right corner is the SE iso', () => {
  const edge = camForRegion(['front', 'right']);
  assert.deepEqual(edge.dir, r6([-Math.SQRT1_2, Math.SQRT1_2, 0]));
  assert.deepEqual(edge.up, [0, 0, 1]);
  assert.equal(core.cubeView(['front', 'right']).projection, null, 'edges keep the current projection');
  const corner = core.cubeView(['top', 'front', 'right']);
  assert.deepEqual(r6([corner.azimuth, corner.elevation]), r6([core.NAMED_VIEWS.perspective.azimuth, core.NAMED_VIEWS.perspective.elevation]));
  const c = camForRegion(['top', 'front', 'right']);
  assert.deepEqual(c.dir, r6([-1 / Math.sqrt(3), 1 / Math.sqrt(3), -1 / Math.sqrt(3)]));
});

test('Clicking TOP: north (+Y) at the screen top, east (+X) to the right', () => {
  const { cam } = camForRegion(['top']);
  const o = new THREE.Vector3(...C).project(cam), n = new THREE.Vector3(C[0], C[1] + 10, C[2]).project(cam), e = new THREE.Vector3(C[0] + 10, C[1], C[2]).project(cam);
  assert.ok(n.y > o.y + 0.05 && Math.abs(n.x - o.x) < 1e-9);
  assert.ok(e.x > o.x + 0.05 && Math.abs(e.y - o.y) < 1e-9);
});

test('Cube cells: center = face, edge cells = edges, corner cells = corners', () => {
  const L = core.cubeLayout(core.setNamedView(core.createViewState(), 'perspective'));
  assert.deepEqual(L.faces.map(f => f.name).sort(), ['front', 'right', 'top']);
  const top = L.faces.find(f => f.name === 'top');
  const sets = top.cells.map(c => c.names.slice().sort().join('+')).sort();
  assert.deepEqual(sets, ['back+left+top', 'back+right+top', 'back+top', 'front+left+top', 'front+right+top', 'front+top', 'left+top', 'right+top', 'top']);
});

test('The cube follows the camera: after orbiting to the north-west, it shows top, back and left', () => {
  const s = core.setNamedView(core.createViewState(), 'perspective');
  core.orbit(s, -Math.PI / 0.008, 0); // half a turn (orbit turns 0.008 rad per px)
  const shown = core.cubeLayout(s).faces.map(f => f.name).sort();
  assert.deepEqual(shown, ['back', 'left', 'top']);
  // And the drawn +Z of the cube matches the camera: top face center is straight up the screen from the cube center.
  const top = core.cubeLayout(s).faces.find(f => f.name === 'top');
  const z = core.gizmoAxes(s).z;
  assert.ok(Math.abs(top.center[0] - z[0]) < 1e-9 && Math.abs(top.center[1] - z[1]) < 1e-9);
});
