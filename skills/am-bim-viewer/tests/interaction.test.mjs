// Click, double-click and inline-SVG behaviour, on the demo model, using the
// same geometry builder and picking code the viewer page runs.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const DATA = JSON.parse(readFileSync(resolve(here, '../../../mods/am-bim-viewer/viewer/demo.json'), 'utf8'));
const byName = n => DATA.elements.find(e => e.name === n);
const MODEL = core.meshBounds(DATA.elements);

function scene(view, aspect = 1.5) {
  const state = core.setNamedView({ ...core.createViewState(), aspect }, view, MODEL);
  const cams = { persp: new THREE.PerspectiveCamera(), ortho: new THREE.OrthographicCamera() };
  const meshes = DATA.elements.map(el => {
    const m = new THREE.Mesh(core.buildElementGeometry(THREE, el), new THREE.MeshBasicMaterial());
    m.userData.el = el;
    m.add(new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry))); // like the page: must never be picked
    m.updateMatrixWorld(true);
    return m;
  });
  const camera = () => core.applyView(THREE, state, cams, aspect);
  const ndcOf = p => { const v = new THREE.Vector3(...p).project(camera()); return { x: v.x, y: v.y }; };
  const pick = ndc => {
    const m = core.pickElement(new THREE.Raycaster(), meshes, new THREE.Vector2(ndc.x, ndc.y), camera());
    return m ? m.userData.el : null;
  };
  return { state, meshes, camera, ndcOf, pick };
}
const center = b => [0, 1, 2].map(i => (b.min[i] + b.max[i]) / 2);

test('Left click picks only the nearest element under the cursor', () => {
  const s = scene('front');
  const door = byName('Entry door (south)');
  // In Front view the door sits in front of the south wall, which hides the slab and the north walls.
  assert.equal(s.pick(s.ndcOf(center(core.elementBounds(door)))).id, door.id);
  const top = scene('top');
  const col = byName('NE corner column');
  assert.equal(top.pick(top.ndcOf([60, 50, 24])).id, col.id, 'Top view: column above slab and walls');
  const slabPoint = top.ndcOf([20, 10, 0]);
  assert.equal(top.pick(slabPoint).name, 'Slab - south wing');
});

test('Demo door sits on the south (-Y) face, mid-way along the south wall', () => {
  const door = core.elementBounds(byName('Entry door (south)'));
  const wall = core.elementBounds(byName('South wall'));
  assert.ok(door.min[1] < wall.min[1], 'door projects past the south face');
  const mid = (wall.min[0] + wall.max[0]) / 2, dc = (door.min[0] + door.max[0]) / 2;
  assert.ok(Math.abs(dc - mid) < 1, 'door center x ' + dc + ' near wall middle ' + mid);
  // In Front view (looking north) the door is in front of the wall: it gets picked.
  const s = scene('front');
  assert.equal(s.pick(s.ndcOf([dc, 0, 3.5])).name, 'Entry door (south)');
});

test('Left click on empty space picks nothing (clears the selection)', () => {
  const s = scene('top');
  assert.equal(s.pick({ x: 0.97, y: -0.97 }), null);
  assert.deepEqual(core.nextSelection(310000, null), { id: null, isChanged: true });
});

test('Hidden categories cannot be picked; the element behind is picked', () => {
  const s = scene('front');
  const door = byName('Entry door (south)');
  const at = s.ndcOf(center(core.elementBounds(door)));
  for (const m of s.meshes) if (m.userData.el.category === 'Doors') m.visible = false;
  assert.equal(s.pick(at).name, 'South wall');
});

test('The two clicks of a double-click do not change the selection twice', () => {
  const door = byName('Entry door (south)');
  const first = core.nextSelection(null, door);
  const second = core.nextSelection(first.id, door);
  assert.deepEqual([first.isChanged, second.isChanged], [true, false]);
});

test('Double-click on an element: target = its box center, box fits the viewport, direction kept', () => {
  for (const aspect of [1.5, 0.6]) {
    for (const [view, name] of [['perspective', 'NE corner column'], ['top', 'NE corner column'], ['front', 'NE corner column'], ['front', 'South wall'], ['perspective', 'South wall']]) {
      const s = scene(view, aspect);
      const az = s.state.azimuth, el = s.state.elevation;
      const col = byName(name);
      Object.assign(s.state, core.dblClickView(s.state, col, MODEL));
      const b = core.elementBounds(col);
      const c = center(b);
      s.state.target.forEach((v, i) => assert.ok(Math.abs(v - c[i]) < 1e-9, view + ' target ' + s.state.target));
      assert.equal(s.state.azimuth, az);
      assert.equal(s.state.elevation, el);
      for (const x of [b.min[0], b.max[0]]) for (const y of [b.min[1], b.max[1]]) for (const z of [b.min[2], b.max[2]]) {
        const p = s.ndcOf([x, y, z]);
        assert.ok(Math.abs(p.x) <= 1 && Math.abs(p.y) <= 1, view + ' aspect ' + aspect + ': corner off screen ' + JSON.stringify(p));
      }
      // The next right-drag orbits around the element center.
      core.orbit(s.state, 50, 10);
      s.state.target.forEach((v, i) => assert.ok(Math.abs(v - c[i]) < 1e-9));
    }
  }
});

test('Double-click on empty space restores the zoom-extents framing', () => {
  const s = scene('perspective');
  const extents = { ...s.state, target: s.state.target.slice() };
  core.zoomAt(s.state, 0.3, 0.5, 0.5, 1.5);
  core.pan(s.state, 80, -40, 600);
  Object.assign(s.state, core.dblClickView(s.state, null, MODEL));
  for (const k of ['distance', 'viewHeight']) assert.ok(Math.abs(s.state[k] - extents[k]) < 1e-9, k);
  s.state.target.forEach((v, i) => assert.ok(Math.abs(v - extents.target[i]) < 1e-9));
});

test('Camera move animation starts at the old view and ends at the new one', () => {
  const s = scene('perspective');
  const a = { ...s.state }, b = core.dblClickView(s.state, byName('NE corner column'), MODEL);
  assert.deepEqual(core.interpolateView(a, b, 0).target, a.target);
  const end = core.interpolateView(a, b, 1);
  end.target.forEach((v, i) => assert.ok(Math.abs(v - b.target[i]) < 1e-9));
  assert.ok(Math.abs(end.distance - b.distance) < 1e-9);
  assert.equal(core.easeInOut(0), 0);
  assert.equal(core.easeInOut(1), 1);
});

test('Ground grid is a scene object at the model base and does not move with the camera', () => {
  const sc = new THREE.Scene();
  const grid = core.createGroundGrid(THREE, MODEL);
  sc.add(grid);
  assert.equal(grid.parent, sc, 'grid lives in the scene graph');
  assert.ok(grid.isMesh && grid.material.depthWrite === false && grid.renderOrder < 0);
  const ext = Math.max(MODEL.max[0] - MODEL.min[0], MODEL.max[1] - MODEL.min[1]);
  assert.ok(grid.position.z <= MODEL.min[2] && MODEL.min[2] - grid.position.z < ext * 1e-3, 'z ' + grid.position.z + ' vs min Z ' + MODEL.min[2]);
  assert.deepEqual([grid.position.x, grid.position.y], [(MODEL.min[0] + MODEL.max[0]) / 2, (MODEL.min[1] + MODEL.max[1]) / 2]);
  assert.deepEqual(core.gridSteps(ext), { minor: 1, major: 10 }, 'demo: 1 ft minor, 10 ft major');
  // Plane normal is world Z: the grid lies in XY.
  const n = new THREE.Vector3(0, 0, 1).transformDirection(grid.matrixWorld);
  assert.ok(n.z > 0.999999);
  const before = grid.matrixWorld.toArray();
  const s = scene('perspective');
  core.orbit(s.state, 120, -40); core.pan(s.state, 30, 10, 600); core.zoomAt(s.state, 0.5, 0.2, 0.1, 1.5);
  s.camera(); sc.updateMatrixWorld(true);
  assert.deepEqual(grid.matrixWorld.toArray(), before, 'camera moves leave the grid where it is');
});

test('Inline SVG preview: Top view puts the NE column top-right, fits the Svg limit', () => {
  const state = core.setNamedView({ ...core.createViewState(), aspect: 640 / 400 }, 'top', MODEL);
  const out = core.renderSvg(DATA.elements, state, { width: 640, height: 400, selected: byName('NE corner column').id });
  assert.ok(out.svg.length < 131072, 'svg chars ' + out.svg.length);
  assert.equal(out.isCut, false);
  assert.ok(out.svg.includes('rgb(255,176,0)'), 'selected element drawn in the highlight color');
  const colGroup = out.svg.split('<g>').find(g => g.includes('NE corner column'));
  const xs = [...colGroup.matchAll(/[ML]([\d.]+) ([\d.]+)/g)].map(m => [Number(m[1]), Number(m[2])]);
  const cx = xs.reduce((a, p) => a + p[0], 0) / xs.length, cy = xs.reduce((a, p) => a + p[1], 0) / xs.length;
  assert.ok(cx > 320 && cy < 200, 'column at (' + cx + ', ' + cy + ') is right of and above the center');
});
