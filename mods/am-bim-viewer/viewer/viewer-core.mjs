// am-bim-viewer core: camera math and Rhino-style input mapping.
//
// ORIENTATION CONTRACT
//   World = Revit / Rhino: right-handed, X = East, Y = North, Z = Up, decimal feet.
//   Model data stays in these coordinates. There is NO root rotation and NO
//   negative scale. three.js is Y-up only by default: we never rely on that.
//   The camera orientation is built explicitly from azimuth / elevation as a
//   right-handed basis (right, up, back), so Top view (looking down -Z) is not
//   a lookAt singularity. camera.up is set to world Z for anything else that
//   reads it.
//
//   azimuth   = angle in the XY plane of the direction target -> camera,
//               measured from +X toward +Y (radians).
//   elevation = angle of that direction above the XY plane (radians).
//
// This file has no imports. The viewer page inlines it; node tests import it.
// Functions that touch three.js take the THREE namespace as an argument.

export const WORLD_UP = [0, 0, 1];
const DEG = Math.PI / 180;

// Named views. Front = camera at -Y looking toward +Y. Right = camera at +X
// looking toward -X. Perspective = south-east iso (camera at +X, -Y, +Z).
export const NAMED_VIEWS = {
  top: { azimuth: -90 * DEG, elevation: 90 * DEG, projection: 'parallel' },
  front: { azimuth: -90 * DEG, elevation: 0, projection: 'parallel' },
  right: { azimuth: 0, elevation: 0, projection: 'parallel' },
  perspective: { azimuth: -45 * DEG, elevation: Math.atan(1 / Math.SQRT2), projection: 'perspective' },
};

// Rhino mouse mapping (Windows defaults), from:
//   https://www.rhino3d.com/docs/guides/modeling/rhino-windows-navigation/
//   https://docs.mcneel.com/rhino/8/help/en-us/seealso/sak_navigate.htm
//   https://docs.mcneel.com/rhino/8/help/en-us/commands/zoom.htm
// Perspective view: right drag = rotate, Shift+right drag = pan.
// Parallel view (Top/Front/Right): right drag = pan, Ctrl+Shift+right drag = rotate.
// Both: Ctrl+right drag up/down = zoom. Wheel = zoom at cursor; Ctrl+wheel = zoom at view center.
// Left button = select. Middle drag = pan (not a Rhino default; added for laptops).
// button follows DOM MouseEvent.button: 0 left, 1 middle, 2 right.
export function mapPointer({ button, shift = false, ctrl = false, isParallel = false }) {
  if (button === 0) return 'select';
  if (button === 1) return 'pan';
  if (button !== 2) return 'none';
  if (ctrl && shift) return 'rotate';
  if (ctrl) return 'zoom';
  if (shift) return 'pan';
  return isParallel ? 'pan' : 'rotate';
}

export function mapWheel({ ctrl = false }) {
  return ctrl ? 'zoom-center' : 'zoom-cursor';
}

export function createViewState() {
  return {
    target: [0, 0, 0],
    azimuth: NAMED_VIEWS.perspective.azimuth,
    elevation: NAMED_VIEWS.perspective.elevation,
    distance: 100,
    viewHeight: 60, // parallel projection: world height of the viewport
    projection: 'perspective',
    fov: 40, // perspective vertical field of view, degrees
    aspect: 1.5, // viewport width / height; the viewer updates it
    sceneCenter: [0, 0, 0], // model bounds, for clipping planes
    sceneRadius: 50,
  };
}

// Right-handed camera basis. r = screen right, u = screen up, d = from target
// toward camera (the camera looks along -d). r x u = d.
export function cameraBasis(azimuth, elevation) {
  const ca = Math.cos(azimuth), sa = Math.sin(azimuth);
  const ce = Math.cos(elevation), se = Math.sin(elevation);
  const d = [ce * ca, ce * sa, se];
  const r = [-sa, ca, 0];
  const u = cross(d, r);
  return { r, u, d };
}

export function cross(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function add(a, b, s = 1) {
  return [a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s];
}

export function cameraPosition(state) {
  const { d } = cameraBasis(state.azimuth, state.elevation);
  return add(state.target, d, state.distance);
}

// Half height of the visible region at the target plane, in world units.
export function halfHeight(state) {
  if (state.projection === 'parallel') return state.viewHeight / 2;
  return state.distance * Math.tan((state.fov * DEG) / 2);
}

export function setNamedView(state, name, bounds) {
  const v = NAMED_VIEWS[name];
  if (!v) throw new Error('Unknown view: ' + name);
  state.azimuth = v.azimuth;
  state.elevation = v.elevation;
  state.projection = v.projection;
  if (bounds) {
    setScene(state, bounds);
    fitBounds(state, bounds);
  }
  return state;
}

function boundsCenterRadius(bounds) {
  const c = [0, 1, 2].map(i => (bounds.min[i] + bounds.max[i]) / 2);
  const ext = [0, 1, 2].map(i => bounds.max[i] - bounds.min[i]);
  return { c, radius: Math.max(1e-6, Math.hypot(ext[0], ext[1], ext[2]) / 2) };
}

// Remember the whole model's extent. Clipping planes use it, so zooming in
// on a detail never moves the camera into the model.
export function setScene(state, bounds) {
  const { c, radius } = boundsCenterRadius(bounds);
  state.sceneCenter = c;
  state.sceneRadius = radius;
  return state;
}

// bounds = { min: [x,y,z], max: [x,y,z] }
// Keeps the view direction; centers the target on the bounds and fits their
// bounding sphere inside the viewport (both width and height).
export function fitBounds(state, bounds, margin = 1.15) {
  const { c, radius: r0 } = boundsCenterRadius(bounds);
  const radius = r0 * margin;
  const aspect = state.aspect > 0 ? state.aspect : 1;
  const halfV = (state.fov * DEG) / 2;
  const halfH = Math.atan(Math.tan(halfV) * aspect);
  state.target = c;
  state.viewHeight = (radius * 2) / Math.min(1, aspect);
  state.distance = radius / Math.sin(Math.min(halfV, halfH));
  return state;
}

// Zoom Selected (Rhino): same direction, target = element center, fitted.
export const frameBounds = fitBounds;

// Smooth camera moves: blend two states, t in 0..1 (eased by the caller).
export function interpolateView(a, b, t) {
  let dAz = b.azimuth - a.azimuth;
  dAz = Math.atan2(Math.sin(dAz), Math.cos(dAz)); // shortest way round
  const geo = (x, y) => x * Math.pow(y / x, t);
  return {
    ...b,
    target: [0, 1, 2].map(i => a.target[i] + (b.target[i] - a.target[i]) * t),
    azimuth: a.azimuth + dAz * t,
    elevation: a.elevation + (b.elevation - a.elevation) * t,
    distance: geo(a.distance, b.distance),
    viewHeight: geo(a.viewHeight, b.viewHeight),
  };
}

export function easeInOut(t) {
  return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
}

const ORBIT_RAD_PER_PX = 0.008;

// Drag (dx right, dy down, in pixels) rotates as a turntable around world Z.
// Convention: the near face of the model follows the cursor ("grab the model").
// Rhino's docs do not state the direction; this matches Rhino's behaviour as
// we know it and three.js OrbitControls. Horizon stays level: no roll ever.
export function orbit(state, dx, dy) {
  state.azimuth -= dx * ORBIT_RAD_PER_PX;
  state.elevation += dy * ORBIT_RAD_PER_PX;
  const lim = 90 * DEG;
  state.elevation = Math.max(-lim, Math.min(lim, state.elevation));
  return state;
}

// Pan so the content under the cursor follows the cursor.
export function pan(state, dx, dy, viewportHeightPx) {
  const { r, u } = cameraBasis(state.azimuth, state.elevation);
  const perPx = (2 * halfHeight(state)) / viewportHeightPx;
  state.target = add(add(state.target, r, -dx * perPx), u, dy * perPx);
  return state;
}

// Ctrl+right drag: up (dy < 0) zooms in.
export function dragZoomFactor(dy) {
  return Math.exp(dy * 0.01);
}

// Scale the view by factor (< 1 zooms in) about the point under (ndcX, ndcY)
// on the target plane. ndc = normalized device coords, -1..1, +y up.
export function zoomAt(state, factor, ndcX = 0, ndcY = 0, aspect = 1) {
  const { r, u } = cameraBasis(state.azimuth, state.elevation);
  const hh = halfHeight(state);
  const p = add(add(state.target, r, ndcX * hh * aspect), u, ndcY * hh);
  state.target = [0, 1, 2].map(i => p[i] + (state.target[i] - p[i]) * factor);
  state.distance *= factor;
  state.viewHeight *= factor;
  return state;
}

// Apply the state to a three.js camera pair. Returns the active camera.
export function applyView(THREE, state, cams, aspect) {
  const { r, u, d } = cameraBasis(state.azimuth, state.elevation);
  const cam = state.projection === 'parallel' ? cams.ortho : cams.persp;
  const hh = halfHeight(state);
  if (cam.isOrthographicCamera) {
    cam.left = -hh * aspect;
    cam.right = hh * aspect;
    cam.top = hh;
    cam.bottom = -hh;
    // Parallel camera sits outside the whole model, whatever the zoom, so the
    // near plane never cuts it. Depth comes from the scene, not the zoom.
    const off = Math.hypot(...[0, 1, 2].map(i => state.target[i] - state.sceneCenter[i]));
    const back = off + state.sceneRadius * 2 + hh;
    cam.position.fromArray(add(state.target, d, back));
    cam.near = Math.max(0.01, back * 1e-4);
    cam.far = back * 2 + state.sceneRadius * 2;
  } else {
    cam.fov = state.fov;
    cam.aspect = aspect;
    cam.position.fromArray(add(state.target, d, state.distance));
    cam.near = Math.max(0.01, state.distance / 1000);
    const off = Math.hypot(...[0, 1, 2].map(i => state.target[i] - state.sceneCenter[i]));
    cam.far = Math.max(state.distance * 100, state.distance + off + state.sceneRadius * 2);
  }
  cam.up.set(WORLD_UP[0], WORLD_UP[1], WORLD_UP[2]);
  const m = new THREE.Matrix4().makeBasis(
    new THREE.Vector3().fromArray(r),
    new THREE.Vector3().fromArray(u),
    new THREE.Vector3().fromArray(d),
  );
  cam.quaternion.setFromRotationMatrix(m);
  cam.updateProjectionMatrix();
  cam.updateMatrixWorld(true);
  return cam;
}

// Screen direction of each world axis for the gizmo: [x right, y up] per axis.
export function gizmoAxes(state) {
  const { r, u } = cameraBasis(state.azimuth, state.elevation);
  return {
    x: [r[0], u[0]],
    y: [r[1], u[1]],
    z: [r[2], u[2]],
  };
}

// Revit internal length is decimal feet.
export function formatLength(ft) {
  if (typeof ft !== 'number' || !isFinite(ft)) return String(ft);
  return ft.toFixed(2) + ' ft (' + (ft * 0.3048).toFixed(3) + ' m)';
}

export function formatParam(value) {
  if (value && typeof value === 'object' && 'v' in value) {
    const unit = value.u;
    if (unit === 'ft') return formatLength(value.v);
    if (unit === 'sq ft') return value.v.toFixed(2) + ' sq ft (' + (value.v * 0.09290304).toFixed(3) + ' m²)';
    if (unit === 'cu ft') return value.v.toFixed(2) + ' cu ft (' + (value.v * 0.0283168466).toFixed(3) + ' m³)';
    return String(value.v) + (unit ? ' ' + unit : '');
  }
  return value === null || value === undefined ? '' : String(value);
}

export function meshBounds(elements) {
  const min = [Infinity, Infinity, Infinity];
  const max = [-Infinity, -Infinity, -Infinity];
  for (const el of elements) {
    const v = (el.mesh && el.mesh.vertices) || [];
    for (let i = 0; i + 2 < v.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        if (v[i + k] < min[k]) min[k] = v[i + k];
        if (v[i + k] > max[k]) max[k] = v[i + k];
      }
    }
  }
  if (min[0] === Infinity) return { min: [-1, -1, -1], max: [1, 1, 1] };
  return { min, max };
}

export function elementBounds(el) {
  return meshBounds([el]);
}

// One flat-shaded three.js geometry per element (Revit coordinates as is).
export function buildElementGeometry(THREE, el) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(el.mesh.vertices, 3));
  g.setIndex(el.mesh.indices);
  const flat = g.toNonIndexed();
  flat.computeVertexNormals();
  flat.computeBoundingSphere();
  return flat;
}

// Left click: the nearest visible element mesh under ndc ({x, y}, -1..1), or
// null for empty space. Child objects (edge lines, outlines) are never picked.
export function pickElement(raycaster, meshes, ndc, camera) {
  raycaster.setFromCamera(ndc, camera);
  const hits = raycaster.intersectObjects(meshes.filter(m => m.visible), false);
  return hits.length ? hits[0].object : null;
}

// Left click selection. A click on the selected element changes nothing, so
// the two clicks of a double-click never redraw the panel twice.
export function nextSelection(currentId, pickedEl) {
  const id = pickedEl ? pickedEl.id : null;
  return { id, isChanged: String(id) !== String(currentId) };
}

// Double-click: on an element, Zoom Selected (keep direction, target = its
// center, fit its box); on empty space, zoom extents. Returns the end state of
// the camera move; the page animates to it.
export function dblClickView(state, pickedEl, modelBounds) {
  const end = { ...state, target: state.target.slice() };
  return fitBounds(end, pickedEl ? elementBounds(pickedEl) : modelBounds);
}

// ---- World-space ground grid ----
// Minor/major spacing from the model size: about 50-500 minor cells across.
export function gridSteps(extent) {
  const minor = Math.pow(10, Math.floor(Math.log10(Math.max(extent, 1e-6) / 50)));
  return { minor, major: minor * 10 };
}

// Placement of the grid for the given (visible) model bounds: in the XY plane
// just below the lowest point, centered on the XY box, fading out at ~1.75x
// the larger XY extent.
export function gridLayout(bounds) {
  const ex = bounds.max[0] - bounds.min[0], ey = bounds.max[1] - bounds.min[1];
  const extent = Math.max(ex, ey, 1e-3);
  const { minor, major } = gridSteps(extent);
  const fade = extent * 1.75;
  return {
    center: [(bounds.min[0] + bounds.max[0]) / 2, (bounds.min[1] + bounds.max[1]) / 2],
    z: bounds.min[2] - extent * 1e-4, // a hair below the base: no z-fighting
    minor, major, fade,
  };
}

// One plane in the scene graph (not a screen overlay). A shader draws the
// lines from world XY with a radial alpha fade, so it has no hard edge.
export function createGroundGrid(THREE, bounds, color = '#f4f4f1') {
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, side: THREE.DoubleSide,
    uniforms: {
      uMinor: { value: 1 }, uMajor: { value: 10 }, uFade: { value: 100 },
      uCenter: { value: new THREE.Vector2() }, uColor: { value: new THREE.Color(color) }, uOpacity: { value: 1 },
    },
    vertexShader: 'varying vec3 vWorld; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
    fragmentShader: [
      'uniform float uMinor; uniform float uMajor; uniform float uFade; uniform vec2 uCenter; uniform vec3 uColor; uniform float uOpacity;',
      'varying vec3 vWorld;',
      'float gridLine(vec2 p, float s) { vec2 q = p / s; vec2 g = abs(fract(q - 0.5) - 0.5) / fwidth(q); return 1.0 - min(min(g.x, g.y), 1.0); }',
      'void main() {',
      '  vec2 p = vWorld.xy;',
      '  float d = length(p - uCenter);',
      '  float fade = 1.0 - smoothstep(uFade * 0.3, uFade, d);',
      '  float a = max(gridLine(p, uMinor) * 0.16, gridLine(p, uMajor) * 0.38) * fade * uOpacity;',
      '  if (a < 0.004) discard;',
      '  gl_FragColor = vec4(uColor, a);',
      '}',
    ].join('\n'),
  });
  const grid = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat); // PlaneGeometry lies in XY: right for Z up
  grid.name = 'ground-grid';
  grid.renderOrder = -1; // drawn before the model
  grid.userData.isGrid = true;
  placeGroundGrid(grid, bounds);
  return grid;
}

export function placeGroundGrid(grid, bounds) {
  const g = gridLayout(bounds);
  grid.position.set(g.center[0], g.center[1], g.z);
  grid.scale.set(g.fade, g.fade, 1);
  const u = grid.material.uniforms;
  u.uMinor.value = g.minor; u.uMajor.value = g.major; u.uFade.value = g.fade;
  u.uCenter.value.set(g.center[0], g.center[1]);
  grid.updateMatrixWorld(true);
  return g;
}

// ---- Scene colors per theme (design/DESIGN-SYSTEM.md, "selected (3D)") ----
// tokens: CSS token values read from the page: v0..v7 ('#rrggbb'), ink, line.
// Night: the selected element turns paper with an ink hairline outline.
// Paper: the inverse, an ink element with a paper hairline outline.
// Hover lifts the category value a little toward the selection value.
export function scenePalette(theme, tokens) {
  const isNight = theme === 'night';
  const steps = {};
  for (const k of [2, 3, 4, 5, 6]) steps[k] = tokens['v' + k];
  const selected = isNight ? tokens.v7 : tokens.v0;
  return {
    theme: isNight ? 'night' : 'paper',
    steps,
    selected,
    outline: isNight ? tokens.v0 : tokens.v7,
    hoverToward: selected,
    hoverLift: 0.22,
    edge: tokens.v0,
    edgeOpacity: isNight ? 0.7 : 0.5,
    grid: tokens.line,
    gizmo: tokens.ink,
  };
}

// ---- Static SVG rendering, for surfaces without WebGL (the inline pane) ----
// Same camera math as the 3D page. Painter's algorithm, flat shading.
// Categories are told apart by VALUE, not hue (design/DESIGN-SYSTEM.md):
// each category gets one step of the gray scale --v2..--v6 (design/tokens.css).
// The 3D page reads the steps from CSS at runtime; VALUE_RGB is the same scale
// as literal RGB for surfaces without CSS (the inline pane SVG, node tests).
export const VALUE_RGB = {
  0: [10, 10, 10], 2: [58, 58, 56], 3: [107, 107, 104], 4: [154, 154, 150], 5: [201, 201, 196], 6: [231, 231, 227], 7: [244, 244, 241],
};
export const CATEGORY_STEP = {
  Floors: 2, Roofs: 3, Walls: 4, Columns: 5, 'Structural Columns': 5, Doors: 6, Windows: 6,
};
const EXTRA_STEPS = [3, 5, 2, 6, 4];

// Category -> value step (2..6), in first-seen order for unknown categories.
export function categoryValues(elements) {
  const out = {};
  let extra = 0;
  for (const el of elements) {
    const cat = el.category || 'Generic';
    if (!(cat in out)) out[cat] = CATEGORY_STEP[cat] || EXTRA_STEPS[extra++ % EXTRA_STEPS.length];
  }
  return out;
}

// Category -> [r, g, b] of its value step.
export function categoryColors(elements) {
  const steps = categoryValues(elements);
  const out = {};
  for (const cat of Object.keys(steps)) out[cat] = VALUE_RGB[steps[cat]].slice();
  return out;
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
}

export function renderSvg(elements, state, opts = {}) {
  const width = opts.width || 640, height = opts.height || 400;
  const hidden = new Set(opts.hidden || []);
  const selected = opts.selected === undefined || opts.selected === null ? null : String(opts.selected);
  const maxTriangles = opts.maxTriangles || 1800;
  const { r, u, d } = cameraBasis(state.azimuth, state.elevation);
  const hh = halfHeight(state);
  const scale = height / 2 / hh;
  const isPersp = state.projection !== 'parallel';
  const light = [-0.35, -0.55, 0.76];
  const cats = categoryColors(elements);
  const tris = [];
  let total = 0;
  for (const el of elements) {
    const cat = el.category || 'Generic';
    if (hidden.has(cat)) continue;
    const v = el.mesh.vertices, ix = el.mesh.indices;
    const isSel = selected !== null && String(el.id) === selected;
    for (let t = 0; t + 2 < ix.length; t += 3) {
      total++;
      const pts = [], world = [];
      let depth = 0, behind = false;
      for (let k = 0; k < 3; k++) {
        const p = [v[ix[t + k] * 3], v[ix[t + k] * 3 + 1], v[ix[t + k] * 3 + 2]];
        world.push(p);
        const q = [p[0] - state.target[0], p[1] - state.target[1], p[2] - state.target[2]];
        const x = q[0] * r[0] + q[1] * r[1] + q[2] * r[2];
        const y = q[0] * u[0] + q[1] * u[1] + q[2] * u[2];
        const z = q[0] * d[0] + q[1] * d[1] + q[2] * d[2];
        if (isPersp && state.distance - z <= 1e-3) behind = true;
        const f = isPersp ? state.distance / Math.max(1e-6, state.distance - z) : 1;
        pts.push([width / 2 + x * f * scale, height / 2 - y * f * scale]);
        depth += z;
      }
      if (behind) continue;
      const n = cross(
        [world[1][0] - world[0][0], world[1][1] - world[0][1], world[1][2] - world[0][2]],
        [world[2][0] - world[0][0], world[2][1] - world[0][1], world[2][2] - world[0][2]]);
      const len = Math.hypot(n[0], n[1], n[2]) || 1;
      const shade = 0.55 + 0.45 * Math.abs((n[0] * light[0] + n[1] * light[1] + n[2] * light[2]) / len);
      // The selected element turns flat paper (--v7), so it reads at a glance.
      const rgb = isSel ? VALUE_RGB[7] : cats[cat].map(c => Math.round(Math.min(255, c * shade)));
      tris.push({ depth: depth / 3, pts, rgb, el, isSel });
    }
  }
  tris.sort((a, b) => a.depth - b.depth); // far first
  const drawn = tris.length > maxTriangles ? tris.slice(tris.length - maxTriangles) : tris;
  // Consecutive triangles of one element share a <g> with a <title> (hover text).
  let body = '';
  let open = null;
  for (const t of drawn) {
    if (t.el !== open) {
      if (open) body += '</g>';
      open = t.el;
      const title = [open.name || open.category, 'ID ' + open.id, open.category, open.type, open.level].filter(Boolean).join(' | ');
      body += '<g><title>' + esc(title) + '</title>';
    }
    const fill = 'rgb(' + t.rgb.join(',') + ')';
    body += '<path d="M' + t.pts.map(p => p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join('L') + 'Z" fill="' + fill + '" stroke="' + fill + '" stroke-width=".6"/>';
  }
  if (open) body += '</g>';
  // The one focal dot: an ink dot ringed in paper at the selected element's center.
  let dot = '';
  const selTris = drawn.filter(t => t.isSel);
  if (selTris.length) {
    let sx = 0, sy = 0, n = 0;
    for (const t of selTris) for (const p of t.pts) { sx += p[0]; sy += p[1]; n++; }
    dot = '<circle cx="' + (sx / n).toFixed(1) + '" cy="' + (sy / n).toFixed(1) + '" r="4.5" fill="rgb(' + VALUE_RGB[0].join(',') + ')" stroke="rgb(' + VALUE_RGB[7].join(',') + ')" stroke-width="1.5"/>';
  }
  // Axis gizmo, bottom-left, without hue: X solid, Y dashed, Z dotted, each labeled.
  const gx = 34, gy = height - 34;
  const ink = opts.ink || 'rgb(' + VALUE_RGB[7].join(',') + ')';
  let gizmo = '';
  for (const [k, lab, dash, w] of [[0, 'X', '', 2], [1, 'Y', '4 3', 1.6], [2, 'Z', '0.1 3.4', 2.2]]) {
    gizmo += '<line x1="' + gx + '" y1="' + gy + '" x2="' + (gx + r[k] * 22).toFixed(1) + '" y2="' + (gy - u[k] * 22).toFixed(1) + '" stroke="' + ink + '" stroke-width="' + w + '" stroke-linecap="round"' + (dash ? ' stroke-dasharray="' + dash + '"' : '') + '/>' +
      '<text x="' + (gx + r[k] * 30).toFixed(1) + '" y="' + (gy - u[k] * 30 + 4).toFixed(1) + '" fill="' + ink + '" font-size="11" font-family="IBM Plex Mono, ui-monospace, Consolas, monospace" font-weight="500" text-anchor="middle">' + lab + '</text>';
  }
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '">' +
    '<rect width="100%" height="100%" fill="' + (opts.background || '#0a0a0a') + '"/>' + body + dot + gizmo + '</svg>';
  return { svg, drawn: drawn.length, total, isCut: drawn.length < tris.length };
}
