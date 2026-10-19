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
  if (bounds) fitBounds(state, bounds);
  return state;
}

// bounds = { min: [x,y,z], max: [x,y,z] }
export function fitBounds(state, bounds, margin = 1.15) {
  const c = [0, 1, 2].map(i => (bounds.min[i] + bounds.max[i]) / 2);
  const ext = [0, 1, 2].map(i => bounds.max[i] - bounds.min[i]);
  const radius = Math.max(1e-6, Math.hypot(ext[0], ext[1], ext[2]) / 2) * margin;
  state.target = c;
  state.viewHeight = radius * 2;
  state.distance = radius / Math.sin((state.fov * DEG) / 2);
  return state;
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
    // Parallel camera sits far back so near clipping never cuts the model.
    const back = Math.max(state.distance, hh * 4);
    cam.position.fromArray(add(state.target, d, back));
    cam.near = 0.01;
    cam.far = back * 4 + hh * 4;
  } else {
    cam.fov = state.fov;
    cam.aspect = aspect;
    cam.position.fromArray(add(state.target, d, state.distance));
    cam.near = Math.max(0.01, state.distance / 1000);
    cam.far = state.distance * 100;
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
