// Pet mode: deterministic fixed steps (a mock clock of dt = 1/60 s). No browser, no real scene.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const DT = 1 / 60;
const flat = { ground: () => 0 };
const walkTo = (p, env, maxSteps = 6000) => { let n = 0; while (p.target && n < maxSteps) { core.petStep(p, DT, env); n++; } return n; };

test('petSurface: an up-facing floor is standable, a wall is not, and a back face is flipped toward the camera', () => {
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(1, 1)); mesh.updateMatrixWorld(true);
  const hit = (nx, ny, nz) => ({ point: new THREE.Vector3(1, 2, 3), face: { normal: new THREE.Vector3(nx, ny, nz) }, object: mesh });
  const down = new THREE.Vector3(0, 0, -1);
  assert.equal(core.petSurface(hit(0, 0, 1), down).isStandable, true, 'floor seen from above');
  assert.equal(core.petSurface(hit(1, 0, 0), down).isStandable, false, 'wall');
  const back = core.petSurface(hit(0, 0, -1), new THREE.Vector3(0, 0, 1));
  assert.equal(back.normal[2], 1, 'a face that points away from the ray is flipped');
  assert.deepEqual(core.petSurface(hit(0, 0, 1), down).point, [1, 2, 3]);
  assert.equal(core.petSurface(null, down), null);
  const slope = Math.sin(59 * Math.PI / 180);
  assert.equal(core.petSurface(hit(0, Math.cos(59 * Math.PI / 180), slope), down).isStandable, false, 'a normal 59 deg above horizontal is too steep');
});

test('petStep: turns first, then walks straight and stops exactly at the target', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]);
  p.heading = Math.PI; // facing the wrong way
  core.petStep(p, DT, flat);
  assert.ok(p.moving && p.pos[0] === 0, 'turns in place while the heading is off by more than the tolerance');
  const n = walkTo(p, flat);
  assert.deepEqual(p.pos, [10, 0, 0], 'arrives at the target');
  assert.equal(p.target, null);
  assert.equal(p.moving, false, 'idle after arrival, so the page can stop drawing');
  assert.ok(n * DT > 10 / core.PET.speed && n * DT < 10 / core.PET.speed + 1.5, 'about speed ft/s plus the turn: ' + n * DT + ' s');
});

test('petStep: takes the short way round when it turns', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [0, 10, 0]); // north = +90 deg
  p.heading = -170 * Math.PI / 180;
  core.petStep(p, DT, flat);
  assert.ok(p.heading < -170 * Math.PI / 180, 'from -170 to +90 the short way is 100 deg clockwise, so the heading decreases');
});

test('petStep: stops in front of a wall', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [20, 0, 0]);
  const env = { ground: () => 0, blocked: (x, y, z, dx, dy, len) => x + len >= 10 }; // a wall at x = 10
  walkTo(p, env);
  assert.equal(p.target, null);
  assert.ok(p.pos[0] > 8 && p.pos[0] < 10, 'stopped just short of the wall: ' + p.pos[0]);
});

test('petStep: follows small steps up and down, stops at an edge, a big drop or a big climb', () => {
  const ramp = { ground: x => (x < 5 ? 0 : 0.5) };
  let p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]); walkTo(p, ramp);
  assert.equal(p.pos[2], 0.5, 'steps up a 0.5 ft kerb (below stepUp)');
  p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]); walkTo(p, { ground: x => (x < 5 ? 0 : null) });
  assert.ok(p.pos[0] < 5.1 && p.target === null, 'stops at an edge (no ground): x ' + p.pos[0]);
  p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]); walkTo(p, { ground: x => (x < 5 ? 0 : -3) });
  assert.ok(p.pos[0] < 5.1, 'stops at a 3 ft drop');
  p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]); walkTo(p, { ground: x => (x < 5 ? 0 : 3) });
  assert.ok(p.pos[0] < 5.1, 'stops at a 3 ft climb');
});

test('petStep: a bigger pet (scale) walks faster and clears bigger steps', () => {
  const small = core.petGo(core.createPet([0, 0, 0], 1), [30, 0, 0]);
  const big = core.petGo(core.createPet([0, 0, 0], 3), [30, 0, 0]);
  const t1 = walkTo(small, flat), t3 = walkTo(big, flat);
  assert.ok(t3 < t1 / 2, 'scale 3 arrives in well under half the time: ' + t1 + ' vs ' + t3);
});

test('petScale grows with the model and is clamped', () => {
  const b = ext => ({ min: [0, 0, 0], max: [ext, 10, 10] });
  assert.equal(core.petScale(b(20)), 1);
  assert.ok(Math.abs(core.petScale(b(100)) - 2) < 1e-9);
  assert.equal(core.petScale(b(1e6)), core.PET.maxScale);
});

test('petPose: a still pose when idle, swinging legs (opposite phase) and a bob while walking', () => {
  const idle = core.petPose({ moving: false, phase: 1 });
  assert.deepEqual(idle, { legL: 0, legR: 0, bob: 0, tail: 0, ear: 0 });
  const w = core.petPose({ moving: true, phase: Math.PI / 2 });
  assert.ok(Math.abs(w.legL) > 0.5 && Math.abs(w.legL + w.legR) < 1e-12, 'legs swing in opposite directions');
  assert.ok(w.bob > 0.05, 'bob at the top of the stride');
});

test('createPetModel + petApply: a group with the named parts, placed and turned', () => {
  const m = core.createPetModel(THREE);
  for (const k of ['legL', 'legR', 'hindL', 'hindR', 'earL', 'earR', 'tail', 'shadow']) assert.ok(m.parts[k], 'part ' + k);
  const p = core.createPet([3, 4, 5], 2); p.heading = Math.PI / 2;
  core.petApply(m, p);
  assert.deepEqual(m.group.position.toArray(), [3, 4, 5]);
  assert.ok(Math.abs(m.group.rotation.z - Math.PI / 2) < 1e-12);
  assert.equal(m.group.scale.x, 2);
  const box = new THREE.Box3().setFromObject(m.group);
  assert.ok(box.max.z - box.min.z > 1.5 && box.max.z - box.min.z < 3, 'about 1 ft x scale 2 tall: ' + (box.max.z - box.min.z));
});

test('petApply: the cat walks with diagonal pairs (front-left with hind-right) and keeps the ear tilt', () => {
  const m = core.createPetModel(THREE);
  const p = core.createPet([0, 0, 0]); p.moving = true; p.phase = Math.PI / 2;
  core.petApply(m, p);
  const { legL, legR, hindL, hindR, earL, earR } = m.parts;
  assert.ok(Math.abs(legL.rotation.y - hindR.rotation.y) < 1e-12 && Math.abs(legR.rotation.y - hindL.rotation.y) < 1e-12, 'diagonal legs swing together');
  assert.ok(legL.rotation.y * legR.rotation.y < 0, 'the two front legs swing in opposite directions');
  assert.ok(earL.rotation.x < 0 && earR.rotation.x > 0, 'ears tilt outward');
});
