// Pet mode: deterministic fixed steps (a mock clock of dt = 1/60 s). No browser, no real scene.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { core } from './load-core.mjs';

const DT = 1 / 60;
const flat = { ground: () => 0 };
// Step until the pet has no target; returns the number of steps and whether it jumped on the way.
const walkTo = (p, env, maxSteps = 6000) => {
  let n = 0, jumped = false;
  while (p.target && n < maxSteps) { core.petStep(p, DT, env); n++; if (p.jump) jumped = true; }
  return { n, jumped };
};
const stepFor = (p, seconds, env = flat) => { for (let i = 0; i < Math.round(seconds / DT); i++) core.petStep(p, DT, env); return p; };

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

test('petStep: turns in an arc, never spins, and stops exactly at the target', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]);
  p.heading = Math.PI; // facing the wrong way
  let prev = p.heading, steps = 0;
  while (p.target && steps < 3000) {
    const x0 = p.pos[0], y0 = p.pos[1];
    core.petStep(p, DT, flat); steps++;
    const turned = Math.abs(Math.atan2(Math.sin(p.heading - prev), Math.cos(p.heading - prev)));
    assert.ok(turned <= core.PET.turnRate * DT + 1e-9, 'never turns faster than turnRate: ' + turned);
    prev = p.heading;
    if (p.target) assert.ok(Math.hypot(p.pos[0] - x0, p.pos[1] - y0) > 0, 'always moving forward while it turns (step ' + steps + ')');
  }
  assert.deepEqual(p.pos, [10, 0, 0], 'arrives at the target');
  assert.equal(p.target, null);
  assert.equal(p.moving, false, 'not moving after arrival');
  assert.ok(steps * DT < 20, 'arrives in a sensible time: ' + steps * DT + ' s');
});

test('petStep: takes the short way round when it turns', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [0, 10, 0]); // north = +90 deg
  p.heading = -170 * Math.PI / 180;
  core.petStep(p, DT, flat);
  assert.ok(p.heading < -170 * Math.PI / 180, 'from -170 to +90 the short way is 100 deg clockwise, so the heading decreases');
});

test('petStep: the feet step while it turns, so it never slides', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [0, 10, 0]);
  const before = p.phase; core.petStep(p, DT, flat);
  assert.ok(p.phase > before, 'the gait phase advances during a turn');
});

test('petStep: a far target is a run, a near one a walk; a run reaches the run speed', () => {
  assert.equal(core.petGo(core.createPet([0, 0, 0]), [3, 0, 0]).run, false);
  const far = core.petGo(core.createPet([0, 0, 0]), [30, 0, 0]);
  assert.equal(far.run, true);
  stepFor(far, 2);
  assert.ok(far.speed > core.PET.speed && far.speed <= core.PET.run + 1e-9, 'speeds up toward the run speed: ' + far.speed);
});

test('petStep: stops in front of a wall that is too high to jump', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [20, 0, 0]);
  const env = { ground: () => 0, blocked: (x, y, z, dx, dy, len) => x + len >= 10 }; // a wall at x = 10, at every height
  walkTo(p, env);
  assert.equal(p.target, null);
  assert.ok(p.pos[0] > 8 && p.pos[0] < 10, 'stopped just short of the wall: ' + p.pos[0]);
});

test('petStep: turns toward a target behind it when a wall is ahead, instead of stopping', () => {
  const p = core.createPet([9, 0, 0]); p.heading = 0;               // facing the wall at x = 10
  core.petGo(p, [0, 0, 0]);                                           // the target is behind it
  const env = { ground: () => 0, blocked: (x, y, z, dx, dy, len) => dx > 0 && x + len >= 10 }; // a wall only in front of it
  walkTo(p, env);
  assert.ok(p.pos[0] < 1, 'turned around and walked to the target: x ' + p.pos[0]);
});

test('petStep: small steps are walked; a ledge, drop or gap within reach is jumped; an edge, big drop or tall ledge stops it', () => {
  const go = ground => { const p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]); const r = walkTo(p, { ground }); return { p, r }; };
  let t = go(x => (x < 5 ? 0 : 0.5));
  assert.equal(t.p.pos[2], 0.5, 'steps up a 0.5 ft kerb (below stepUp)'); assert.equal(t.r.jumped, false);
  t = go(x => (x < 5 ? 0 : 2));
  assert.deepEqual(t.p.pos, [10, 0, 2], 'jumps up a 2 ft ledge and walks on'); assert.equal(t.r.jumped, true);
  t = go(x => (x < 5 ? 0 : -3));
  assert.deepEqual(t.p.pos, [10, 0, -3], 'jumps down a 3 ft drop'); assert.equal(t.r.jumped, true);
  t = go(x => (x < 5 || x > 6.5 ? 0 : null)); // a gap from x = 5 to 6.5
  assert.equal(t.r.jumped, true, 'jumps a gap about 1.5 ft wide'); assert.deepEqual(t.p.pos, [10, 0, 0], 'and lands on the far side');
  t = go(x => (x < 5 ? 0 : null));
  assert.ok(t.p.pos[0] < 5.1 && t.p.target === null, 'stops at an edge with no ground ahead: x ' + t.p.pos[0]);
  t = go(x => (x < 5 ? 0 : -20));
  assert.ok(t.p.pos[0] < 5.1 && t.r.jumped === false, 'stops at a 20 ft drop');
  t = go(x => (x < 5 ? 0 : 4));
  assert.ok(t.p.pos[0] < 5.1 && t.r.jumped === false, 'stops at a 4 ft ledge (jumpUp is ' + core.PET.jumpUp + ')');
});

test('petStep: a jump is an arc that peaks above the landing height and lands on the ground height', () => {
  const p = core.petGo(core.createPet([0, 0, 0]), [10, 0, 0]);
  let peak = -Infinity, sawJump = false;
  const env = { ground: x => (x < 5 ? 0 : 2) };
  for (let i = 0; i < 1500 && p.target; i++) { core.petStep(p, DT, env); if (p.jump) { sawJump = true; peak = Math.max(peak, p.pos[2]); } }
  assert.ok(sawJump && peak > 2, 'peaks above the landing height: ' + peak);
  assert.equal(p.pos[2], 2);
});

test('petStep: a bigger pet (scale) moves faster', () => {
  const small = core.petGo(core.createPet([0, 0, 0], 1), [30, 0, 0]);
  const big = core.petGo(core.createPet([0, 0, 0], 3), [30, 0, 0]);
  const t1 = walkTo(small, flat).n, t3 = walkTo(big, flat).n;
  assert.ok(t3 < t1 / 2, 'scale 3 arrives in well under half the time: ' + t1 + ' vs ' + t3);
});

test('petScale grows with the model and is clamped', () => {
  const b = ext => ({ min: [0, 0, 0], max: [ext, 10, 10] });
  assert.equal(core.petScale(b(20)), 1);
  assert.ok(Math.abs(core.petScale(b(100)) - 2) < 1e-9);
  assert.equal(core.petScale(b(1e6)), core.PET.maxScale);
});

test('gait: a four-beat lateral sequence, with exactly three feet on the ground at any time', () => {
  const stance = u => ((u % 1) + 1) % 1 < core.GAIT.stance;
  for (let i = 0; i < 400; i++) {
    const ph = 0.013 + i * 0.0157; // avoids the exact boundaries
    const on = ['hl', 'fl', 'hr', 'fr'].filter(k => stance((ph + core.GAIT[k]) / (2 * Math.PI))).length;
    assert.equal(on, 3, 'three feet stand at phase ' + ph);
  }
  // footfall order: a foot lands when phase + offset reaches a whole cycle
  const landAt = k => (((2 * Math.PI - core.GAIT[k]) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  const order = ['hl', 'fl', 'hr', 'fr'].sort((a, b) => landAt(a) - landAt(b));
  assert.deepEqual(order, ['hl', 'fl', 'hr', 'fr'], 'hind left, fore left, hind right, fore right');
});

test('legCycle: the foot goes back on the ground in stance, and the knee bends to lift it in swing', () => {
  const stanceMid = core.legCycle(2 * Math.PI * core.GAIT.stance * 0.5);
  const swingMid = core.legCycle(2 * Math.PI * (core.GAIT.stance + (1 - core.GAIT.stance) / 2));
  assert.ok(Math.abs(stanceMid.hip) < 1e-9 && stanceMid.knee < 0.2, 'mid-stance: leg vertical, nearly straight');
  assert.ok(swingMid.knee > 0.8, 'mid-swing: knee bent to lift the foot: ' + swingMid.knee);
  assert.ok(core.legCycle(0).hip < 0 && core.legCycle(2 * Math.PI * 0.74).hip > 0, 'stance moves the foot from front to back');
});

test('petPose: still when idle; the legs swing while walking; the run bounds; a jump reaches forward', () => {
  const idle = core.petPose({ moving: false });
  for (const k of ['flHip', 'frHip', 'hlHip', 'hrHip', 'flKnee', 'frKnee', 'hlKnee', 'hrKnee', 'bob', 'roll', 'pitch', 'drop']) assert.equal(idle[k], 0, k);
  assert.equal(idle.eyes, 1, 'eyes open');
  const w = core.petPose({ moving: true, phase: 1.1 });
  assert.ok(Math.abs(w.flHip) + Math.abs(w.hlHip) > 0.1 && w.bob >= 0, 'legs swing and the body bobs while walking');
  const run = core.petPose({ moving: true, run: true, phase: 1.1 });
  assert.equal(run.flHip, run.frHip, 'a bound: the two front legs move together');
  assert.equal(run.hlHip, run.hrHip, 'and the two hind legs together');
  assert.ok(run.tailPitch < -0.5 && run.earBack > 0.5, 'tail streams back, ears go back');
  const air = core.petPose({ moving: true, jump: { t: 0.5 }, phase: 0 });
  assert.ok(air.flHip < -0.5 && air.hlHip > 0.5, 'in the air: front legs forward, hind legs back');
});

test('idle: stand, then sit, then an action, then sit again; a long rest ends in sleep; a click wakes it', () => {
  const p = core.createPet([0, 0, 0]); const seen = [];
  const rand = () => 0.99; // always the last action (yawn)
  const run = seconds => {
    for (let i = 0; i < Math.round(seconds / DT); i++) { core.petStep(p, DT, { ...flat, rand }); if (seen[seen.length - 1] !== p.act) seen.push(p.act); }
  };
  run(1.4); assert.equal(p.act, 'stand', 'still standing before sitAfter');
  run(0.3); assert.equal(p.act, 'sit', 'sits after about ' + core.PET.sitAfter + ' s');
  run(1.1); assert.equal(p.act, 'yawn', 'then an action (rand picks the last: yawn)');
  run(core.PET_ACTS.yawn + 0.1); assert.equal(p.act, 'sit', 'back to sitting when the action ends');
  run(core.PET.sleepAfter + 3); assert.equal(p.act, 'sleep', 'sleeps after a long rest');
  run(20); assert.equal(p.act, 'sleep', 'and stays asleep');
  core.petGo(p, [3, 0, 0]);
  assert.equal(p.act, 'stand', 'a new target wakes it'); assert.equal(p.idleT, 0);
  assert.ok(seen.includes('sit') && seen.includes('yawn') && seen.includes('sleep'));
});

test('idle: the redraw rate is low when the cat is still, and the three actions are lick, groom and yawn', () => {
  assert.equal(core.petFps({ moving: true }), 60);
  assert.equal(core.petFps({ moving: false, jump: { t: 0 } }), 60);
  assert.equal(core.petFps({ moving: false, act: 'lick' }), 30);
  assert.equal(core.petFps({ moving: false, act: 'sleep' }), 8);
  assert.equal(core.petFps({ moving: false, act: 'sit' }), 8);
  assert.deepEqual(Object.keys(core.PET_ACTS).sort(), ['groom', 'lick', 'yawn']);
});

test('createPetModel + petApply: a group with the named parts, placed and turned', () => {
  const m = core.createPetModel(THREE);
  for (const k of ['legL', 'legR', 'hindL', 'hindR', 'earL', 'earR', 'tail', 'shadow', 'head', 'mouth', 'tongue']) assert.ok(m.parts[k], 'part ' + k);
  assert.equal(m.parts.eyes.length, 2, 'two eyes');
  for (const k of ['legL', 'legR', 'hindL', 'hindR']) assert.ok(m.parts[k].userData.knee, k + ' has a knee');
  const p = core.createPet([3, 4, 5], 2); p.heading = Math.PI / 2;
  core.petApply(m, p);
  assert.deepEqual(m.group.position.toArray(), [3, 4, 5]);
  assert.ok(Math.abs(m.group.rotation.z - Math.PI / 2) < 1e-12);
  assert.equal(m.group.scale.x, 2);
  const box = new THREE.Box3().setFromObject(m.group);
  assert.ok(box.max.z - box.min.z > 1.5 && box.max.z - box.min.z < 3, 'about 1 ft x scale 2 tall: ' + (box.max.z - box.min.z));
});

test('petApply: a sleeping cat lies low with its eyes closed; a yawning cat shows its mouth; the legs are at four points of the cycle', () => {
  const m = core.createPetModel(THREE), p = core.createPet([0, 0, 0]);
  p.act = 'sleep'; core.petApply(m, p);
  assert.ok(m.group.position.z < 0, 'the body drops: ' + m.group.position.z);
  assert.ok(m.parts.eyes.every(e => e.scale.z <= 0.0601), 'eyes closed');
  assert.equal(m.parts.mouth.visible, false);
  p.act = 'yawn'; p.actT = 1.3; core.petApply(m, p);
  assert.equal(m.parts.mouth.visible, true, 'mouth open in the middle of a yawn');
  const w = core.createPet([0, 0, 0]); w.moving = true; w.phase = 1.1; w.w = 1; core.petApply(m, w);
  const hips = ['hindL', 'legL', 'hindR', 'legR'].map(k => m.parts[k].rotation.y.toFixed(3));
  assert.equal(new Set(hips).size, 4, 'the four legs are at four different points of the cycle');
});
