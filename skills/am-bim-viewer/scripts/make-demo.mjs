// Writes the demo dataset: a chiral L-shaped "building" in Revit coordinates
// (X = East, Y = North, Z = Up, feet). A mirrored or rotated viewer shows it
// at once: the long wing runs west-east along the south, the short wing runs
// north on the EAST end, the door is on the SOUTH face, the tall column is at
// the NE corner, and wall heights differ: W 10, S 12, E 16, N 18-20 ft.
//
// Usage: node make-demo.mjs [out.json]
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const out = process.argv[2] || resolve(here, '../../../mods/am-bim-viewer/viewer/demo.json');

// Axis-aligned box as a closed triangle mesh, outward CCW winding.
function box(x0, y0, z0, x1, y1, z1) {
  const v = [
    x0, y0, z0, x1, y0, z0, x1, y1, z0, x0, y1, z0, // bottom 0-3
    x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y1, z1, // top 4-7
  ];
  const i = [
    0, 2, 1, 0, 3, 2, // bottom (-Z)
    4, 5, 6, 4, 6, 7, // top (+Z)
    0, 1, 5, 0, 5, 4, // south (-Y)
    2, 3, 7, 2, 7, 6, // north (+Y)
    1, 2, 6, 1, 6, 5, // east (+X)
    3, 0, 4, 3, 4, 7, // west (-X)
  ];
  return { vertices: v, indices: i };
}

const T = 0.75; // wall thickness, ft
const ft = v => ({ v: Math.round(v * 1000) / 1000, u: 'ft' });
let nextId = 310000;
const elements = [];
function add(category, name, family, type, mesh, params) {
  elements.push({ id: nextId++, category, name, family, type, level: 'Level 1', params, mesh });
}

// Floor slab: two rectangles making the L. Top at z = 0.
add('Floors', 'Slab - south wing', 'Floor', 'Generic 12"', box(0, 0, -1, 60, 20, 0),
  { Thickness: ft(1), Area: { v: 1200, u: 'sq ft' }, Mark: 'F1' });
add('Floors', 'Slab - east wing', 'Floor', 'Generic 12"', box(40, 20, -1, 60, 50, 0),
  { Thickness: ft(1), Area: { v: 600, u: 'sq ft' }, Mark: 'F2' });

// Walls along the L perimeter, each with its own height.
//   (0,0) -> (60,0) -> (60,50) -> (40,50) -> (40,20) -> (0,20) -> (0,0)
const walls = [
  ['South wall', box(0, 0, 0, 60, T, 12), 12, 60, 'W-S'],
  ['East wall', box(60 - T, 0, 0, 60, 50, 16), 16, 50, 'W-E'],
  ['North wall (east wing)', box(40, 50 - T, 0, 60, 50, 20), 20, 20, 'W-N1'],
  ['Inner wall (west face of east wing)', box(40, 20, 0, 40 + T, 50, 14), 14, 30, 'W-I'],
  ['North wall (south wing)', box(0, 20 - T, 0, 40, 20, 18), 18, 40, 'W-N2'],
  ['West wall', box(0, 0, 0, T, 20, 10), 10, 20, 'W-W'],
];
for (const [name, mesh, h, len, mark] of walls) {
  add('Walls', name, 'Basic Wall', 'Generic - 9"', mesh,
    { 'Unconnected Height': ft(h), Length: ft(len), Width: ft(T), Mark: mark, 'Base Constraint': 'Level 1' });
}

// Door on the SOUTH face, at the middle of the south wall (x 28.5-31.5). Sticks out of the wall on both sides.
add('Doors', 'Entry door (south)', 'Single-Flush', '36" x 84"', box(28.5, -0.2, 0, 31.5, T + 0.2, 7),
  { Width: ft(3), Height: ft(7), Mark: 'D1', 'Facing': 'South (-Y)' });

// Tall column at the NE corner. Tallest object in the model.
add('Columns', 'NE corner column', 'Rectangular Column', '24" x 24"', box(59, 49, 0, 61, 51, 24),
  { Height: ft(24), Width: ft(2), Depth: ft(2), Mark: 'C-NE' });

// North arrow marker: a thin wedge pointing +Y, west of the building.
add('Generic Models', 'North arrow', 'North Arrow', 'Wedge',
  { vertices: [-12, 0, 0.1, -8, 0, 0.1, -10, 10, 0.1], indices: [0, 1, 2] },
  { Note: 'Tip points to +Y (North)' });

const data = {
  schema: 'am-bim-viewer/1',
  units: 'ft',
  source: { title: 'Demo L-building (orientation test)', generator: 'make-demo.mjs' },
  elements,
  annotations: [
    { text: 'N (+Y)', position: [-10, 12, 0] },
    { text: 'East (+X)', position: [68, 10, 0] },
    { text: 'South door', position: [30, -6, 0] },
    { text: 'NE column', position: [60, 50, 26] },
  ],
};

writeFileSync(out, JSON.stringify(data, null, 1));
console.log('Wrote ' + elements.length + ' elements to ' + out);
