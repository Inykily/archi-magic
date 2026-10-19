// Mutation check: break the shipped core in known ways and prove the tests go
// red for each one, and stay green for an unchanged copy (control).
// Usage: node tests/mutate.mjs   (exit 1 if any mutant survives)
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const shipped = resolve(here, '../../../mods/am-bim-viewer/viewer/viewer-core.mjs');
const source = readFileSync(shipped, 'utf8');
const outDir = join(tmpdir(), 'am-bim-viewer-mutants');
mkdirSync(outDir, { recursive: true });

const MUTANTS = [
  ['control (no change)', null, null],
  ['three.js default Y-up camera (camera.up = +Y, lookAt)',
    'cam.quaternion.setFromRotationMatrix(m);',
    'cam.up.set(0, 1, 0); cam.lookAt(state.target[0], state.target[1], state.target[2]);'],
  ['flip camera.up to -Z and use lookAt',
    'cam.quaternion.setFromRotationMatrix(m);',
    'cam.up.set(0, 0, -1); cam.lookAt(state.target[0], state.target[1], state.target[2]);'],
  ['swap Y and Z axes in the camera direction',
    'const d = [ce * ca, ce * sa, se];', 'const d = [ce * ca, se, ce * sa];'],
  ['mirror: left-handed basis (u = r x d)', 'const u = cross(d, r);', 'const u = cross(r, d);'],
  ['negate screen right', 'const r = [-sa, ca, 0];', 'const r = [sa, -ca, 0];'],
  ['orbit direction reversed', 'state.azimuth -= dx * ORBIT_RAD_PER_PX;', 'state.azimuth += dx * ORBIT_RAD_PER_PX;'],
  ['parallel views rotate on plain right drag', "return isParallel ? 'pan' : 'rotate';", "return 'rotate';"],
  ['Ctrl+right drag pans instead of zooming', "if (ctrl) return 'zoom';", "if (ctrl) return 'pan';"],
  ['wheel zooms about the center, not the cursor', 'const p = add(add(state.target, r, ndcX * hh * aspect), u, ndcY * hh);', 'const p = state.target;'],
  ['parallel camera depth tied to zoom (camera dives into the model)',
    'const back = off + state.sceneRadius * 2 + hh;', 'const back = Math.max(state.distance, hh * 4);'],
  ['pick the farthest hit instead of the nearest',
    'return hits.length ? hits[0].object : null;', 'return hits.length ? hits[hits.length - 1].object : null;'],
  ['picking ignores hidden categories', 'meshes.filter(m => m.visible)', 'meshes'],
  ['double-click on empty space keeps the current zoom',
    'return fitBounds(end, pickedEl ? elementBounds(pickedEl) : modelBounds);', 'return pickedEl ? fitBounds(end, elementBounds(pickedEl)) : end;'],
  ['frame ignores a narrow viewport (aspect)',
    'state.viewHeight = (radius * 2) / Math.min(1, aspect);', 'state.viewHeight = radius * 2;'],
  ['ground grid at mid-height instead of the base',
    'z: bounds.min[2] - extent * 1e-4,', 'z: (bounds.min[2] + bounds.max[2]) / 2,'],
  ['repeat click on the selected element counts as a change',
    'isChanged: String(id) !== String(currentId)', 'isChanged: true'],
];

const tests = ['orientation.test.mjs', 'camera-input.test.mjs', 'interaction.test.mjs'].map(f => join(here, f));
let survivors = 0;
for (const [name, from, to] of MUTANTS) {
  let text = source;
  if (from !== null) {
    const n = source.split(from).length - 1;
    if (n !== 1) throw new Error('Mutation "' + name + '" matched ' + n + ' times; update the table.');
    text = source.replace(from, () => to);
  }
  const file = join(outDir, name.replace(/[^a-z0-9]+/gi, '-') + '.mjs');
  writeFileSync(file, text);
  const run = spawnSync(process.execPath, ['--test', ...tests], {
    env: { ...process.env, AM_CORE_PATH: file }, encoding: 'utf8', cwd: resolve(here, '..'),
  });
  const pass = Number((run.stdout.match(/^# pass (\d+)/m) || [])[1]);
  const fail = Number((run.stdout.match(/^# fail (\d+)/m) || [])[1]);
  const isControl = from === null;
  const ok = isControl ? fail === 0 && pass > 0 : fail > 0;
  if (!ok) survivors++;
  console.log((ok ? 'OK   ' : 'BAD  ') + name.padEnd(52) + ' pass=' + pass + ' fail=' + fail + (isControl ? ' (must be all green)' : ' (must go red)'));
}
console.log(survivors === 0 ? 'All mutants killed; control green.' : survivors + ' mutant(s) survived.');
process.exit(survivors === 0 ? 0 : 1);
