// Typed gumball input: architect-unit parser, exact (unsnapped) apply, and side-panel values.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { core } from './load-core.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const DATA = JSON.parse(readFileSync(resolve(here, '../../../mods/am-bim-viewer/viewer/demo.json'), 'utf8'));
const col = DATA.elements.find(e => e.name === 'NE corner column');
const r6 = v => Math.round(v * 1e6) / 1e6;

test('parseLength: decimal feet, feet-inches with fractions, inches only, metric, negatives', () => {
  const table = [
    ['2.5', 2.5], ['-2.5', -2.5], ['.5', 0.5], ['0', 0],
    ["2'", 2], ['2\'6"', 2.5], ['2\' 6"', 2.5], ['2\'-6"', 2.5], ["2'6", 2.5],
    ['2\'-6 1/2"', 2 + 6.5 / 12], ['2\'6-1/2"', 2 + 6.5 / 12], ['-2\'6"', -2.5],
    ['30"', 2.5], ['6 1/2"', 6.5 / 12], ['1/2"', 0.5 / 12], ['-30"', -2.5], ['3.5"', 3.5 / 12],
    ['750mm', 750 / 304.8], ['0.75m', 0.75 / 0.3048], ['75cm', 75 / 30.48], ['-750 mm', -750 / 304.8], ['1M', 1 / 0.3048],
  ];
  const got = table.map(([s]) => { const r = core.parseLength(s); return [s, r.error ? r.error : r6(r.ft)]; });
  assert.deepEqual(got, table.map(([s, v]) => [s, r6(v)]));
});

test('parseLength: invalid input gives a plain-words error', () => {
  for (const s of ['', 'abc', '2x', "2''", '5 ft 3', '1/0"', '--2', "'", '"', '2"6\'']) {
    const r = core.parseLength(s);
    assert.ok(r.error && r.ft === undefined, 'should reject: ' + JSON.stringify(s) + ' got ' + JSON.stringify(r));
    assert.match(r.error, /Type a length/);
  }
});

test('parseAngle and the readout format', () => {
  assert.deepEqual(['15', '-90', '22.5', '+45', '30°', '10 deg'].map(s => core.parseAngle(s).deg), [15, -90, 22.5, 45, 30, 10]);
  assert.ok(core.parseAngle('east').error);
  assert.equal(core.formatFeetInches(2.5), '2\'-6"');
  assert.equal(core.formatFeetInches(2 + 6.5 / 12), '2\'-6 1/2"');
  assert.equal(core.formatFeetInches(-0.25), '-0\'-3"');
  assert.equal(core.typedReadout('x', 2.5), 'move x +2\'-6" (2.500 ft)');
  assert.equal(core.typedReadout('y', -0.5), 'move y -0\'-6" (-0.500 ft)');
  assert.equal(core.typedReadout('rz', 15), 'rotate 15 deg');
});

test('Enter applies typed values exactly, without snapping, added to the pending change', () => {
  const edits = core.createEdits();
  core.applyTyped(edits, col, 'x', core.parseLength('2\'-6 1/2"').ft); // 2.5417, not a 1/2 ft step
  core.applyTyped(edits, col, 'x', 0.1);
  core.applyTyped(edits, col, 'rz', core.parseAngle('22.5').deg);
  const [item] = core.exportTransforms(edits).items;
  // 2'-6 1/2" + 0.1 ft = 2.641667 ft, exported to 4 places; a snapped value would be 2.5 or 3.
  assert.deepEqual([item.move, item.rotateZ], [[2.6417, 0, 0], 22.5]);
});

test('Side-panel fields set absolute values and round-trip into the exported JSON', () => {
  const edits = core.createEdits();
  core.applyTyped(edits, col, 'y', 4);
  core.setEditValues(edits, col, { move: [1.25, -3, 0.5], rotateZ: -90 });
  const b = core.elementBounds(col);
  assert.deepEqual(core.exportTransforms(edits), {
    kind: 'element-transforms', source: 'am-bim-viewer', units: 'ft',
    items: [{ id: col.id, name: col.name, category: col.category, move: [1.25, -3, 0.5], rotateZ: -90, pivot: [0, 1, 2].map(i => (b.min[i] + b.max[i]) / 2) }],
  });
  core.setEditValues(edits, col, { move: [0, 0, 0], rotateZ: 0 });
  assert.deepEqual(core.exportTransforms(edits).items, [], 'zeroing every field removes the row');
});

test('parseLength: arithmetic with spaces around + - * / (precedence, units, scalars)', () => {
  const table = [
    ["10' - 3\"", 10 - 3 / 12], ["2'6\" + 1'", 3.5], ["12'6\" / 2", 6.25], ["3 * 2'", 6], ["2' * 3", 6],
    ["10' - 3\" / 2", 10 - 1.5 / 12], ["1' + 2' * 3", 7], ["750mm + 0.25m", (750 + 250) / 304.8],
    ["-2' + 5'", 3], ["2.5 - 0.5", 2], ["10' - 3/2\"", 10 - 1.5 / 12],
  ];
  const got = table.map(([s]) => { const r = core.parseLength(s); return [s, r.error ? r.error : r6(r.ft)]; });
  assert.deepEqual(got, table.map(([s, v]) => [s, r6(v)]));
  // Without spaces, 10'-3/2" stays ordinary feet-inches notation (10 ft 1 1/2 in), not arithmetic.
  assert.equal(r6(core.parseLength("10'-3/2\"").ft), r6(10 + 1.5 / 12));
});

test('parseLength: arithmetic errors are plain words, never a number', () => {
  for (const [s, re] of [["2' * 3'", /Multiply by a plain number only/], ["12' / 2'", /Divide by a plain number only/],
                         ["12' / 0", /Cannot divide by zero/], ["2' + east", /Cannot read "east"/], ["2' +", /Type a length/]]) {
    const r = core.parseLength(s);
    assert.ok(r.error && r.ft === undefined, 'should reject: ' + s);
    assert.match(r.error, re);
  }
});

test('parseAngle: arithmetic', () => {
  assert.deepEqual(['90 - 15', '45 + 45', '180 / 4', '15 * 2'].map(s => core.parseAngle(s).deg), [75, 90, 45, 30]);
  assert.match(core.parseAngle('90 / 0').error, /Cannot divide by zero/);
});

test('Typing during a drag: digits, sign, dot and unit marks start typed entry; other keys do not', () => {
  const starts = ['0', '7', '.', '-', '+', "'", '"'].map(k => core.dragTypingStart(k));
  assert.deepEqual(starts, ['0', '7', '.', '-', '+', "'", '"']);
  const ignored = ['a', 'Escape', 'Shift', 'Enter', ' ', 'ArrowUp', '*', '/', 'Tab'].map(k => core.dragTypingStart(k));
  assert.deepEqual(ignored, ignored.map(() => null));
});
