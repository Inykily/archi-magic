// am-bim-viewer mod.
//
// What a mod surface can draw (plugin-authoring types, Claude Code 2.1.299):
// a Pane is a tree of Box/Text/Button/Select/Svg/... elements; the desktop
// `Svg` element is drawn as an image, or in a sandboxed frame WITHOUT scripts
// (`isInteractive` enables hover and <title> tooltips only); a `Client`
// surface module draws only the same character-cell elements. No surface runs
// WebGL or page scripts, so the live 3D viewer cannot run inside a pane.
//
// So the mod has two parts:
// 1. /bim-view builds the self-contained three.js page and opens it in the
//    app's Browser pane (via the Claude_Browser MCP server when the engine
//    has it connected) or tells the model to open it there.
// 2. An inline "BIM view" pane in the session: a static SVG drawing of the
//    model from the same camera math, with buttons for the named views,
//    rotate and zoom steps, category toggles, an element picker and its data.
import type { EngineInterface, Register } from 'claude-code'

import type { BimPaneView } from '../types'
import { buildViewerHtml } from '../viewer/build.mjs'
import {
  createViewState, setNamedView, zoomAt, meshBounds, elementBounds, renderSvg, formatParam, categoryColors,
} from '../viewer/viewer-core.mjs'

const COMMAND = 'bim-view'
const PANE_ID = 'am-bim-view'
const PANE = { plugin: 'am-bim-viewer', key: 'pane' } as const

type BimElement = {
  id: number | string
  category?: string
  name?: string
  family?: string
  type?: string
  level?: string
  params?: Record<string, unknown>
  mesh: { vertices: number[]; indices: number[] }
}
type BimData = { source?: { title?: string; view?: string }; elements: BimElement[] }

export function parseArgs(raw: string): { input: string | undefined; isOpen: boolean } {
  const words = raw.match(/"[^"]*"|\S+/g) ?? []
  let input: string | undefined
  let isOpen = false
  for (const w of words) {
    if (w === '--open') isOpen = true
    else if (input === undefined) input = w.replace(/^"|"$/g, '')
  }
  return { input, isOpen }
}

function isAbsolute(p: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(p) || p.startsWith('/') || p.startsWith('\\\\')
}

function join(dir: string, file: string): string {
  const sep = dir.includes('\\') ? '\\' : '/'
  return dir.replace(/[\\/]+$/, '') + sep + file
}

export function fileUrl(path: string): string {
  const p = path.replace(/\\/g, '/')
  return 'file://' + (p.startsWith('/') ? '' : '/') + encodeURI(p).replace(/#/g, '%23')
}

// Model data for the pane, by file. A hot reload empties it; the pane reads
// the file again then.
const loaded = new Map<string, BimData>()

async function openInBrowserPane($: EngineInterface, url: string): Promise<boolean> {
  try {
    const r = await $.mcp.call('Claude_Browser', 'preview_start', { url })
    return r.isError !== true
  } catch {
    return false
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: 'Show a Revit JSON export in 3D: inline pane plus the interactive viewer (no path: demo model)',
      argumentHint: '[path/to/model.json] [--open]',
    })
    return next(e)
  })

  on('command.run', { command: COMMAND }, async ($, e) => {
    const { input, isOpen } = parseArgs(e.args)
    const viewerDir = join($.plugin.root, 'viewer')
    const cwd = await $.session.cwd()
    const source = input === undefined ? join(viewerDir, 'demo.json') : isAbsolute(input) ? input : join(cwd, input)
    const output = source.replace(/\.json$/i, '') + '.viewer.html'

    let data: BimData
    try {
      data = JSON.parse(await $.fs.read(source)) as BimData
    } catch (err) {
      const why = err instanceof Error ? err.message : String(err)
      return { text: 'Cannot read the BIM JSON at ' + source + '. ' + why + ' (The mod cannot read files over 4 MiB: use skills/am-bim-viewer/scripts/build-viewer.mjs with node.)' }
    }

    let html: string
    try {
      html = buildViewerHtml({
        template: await $.fs.read(join(viewerDir, 'template.html')),
        core: await $.fs.read(join(viewerDir, 'viewer-core.mjs')),
        data,
      })
    } catch (err) {
      return { text: 'Cannot build the viewer. ' + (err instanceof Error ? err.message : String(err)) }
    }
    await $.fs.write(output, html)
    loaded.set(source, data)

    const count = data.elements.length
    const url = fileUrl(output)
    await $.state.set(PANE, { source, htmlUrl: url, view: 'perspective', turns: 0, zoom: 1, hidden: [], selected: null })
    await $.ui.open({ id: PANE_ID, title: 'BIM view' })

    let opened: string
    if (isOpen) {
      const isWindows = (await $.env.get('OS')) === 'Windows_NT'
      const target = isWindows ? output.replace(/\//g, '\\') : output
      const ran = await $.process.run(isWindows ? ['explorer.exe', target] : ['open', target]).catch(() => undefined)
      // explorer.exe exits 1 even on success; only a failure to start is a failure.
      opened = ran === undefined ? ' Could not start the default browser.' : ' Opened in the default browser.'
    } else {
      opened = (await openInBrowserPane($, url)) ? ' Opened in the Browser pane.' : ''
    }
    $.ui.toast('BIM view ready: ' + count + ' elements')
    return {
      text: 'BIM view: ' + count + ' elements. Viewer page: ' + output + '.' + opened,
      context: opened === ''
        ? ['The am-bim-viewer page is at ' + url + ' . Open it in the Browser pane if a Browser tool is available (preview_start with that url); otherwise give the person the path. An inline BIM view pane is open in the session.']
        : [],
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { text: 'The /bim-view command failed: ' + String(next.error?.message ?? next.error?.kind ?? 'unknown error') },
  )

  on('ui.render', { component: 'Pane', requestId: PANE_ID }, async ($, e) => {
    const ui = $.ui.resolve(e)
    const { Box, Text, Button } = ui
    const Select = 'Select' in ui ? ui.Select : undefined // the mobile app has no Select
    const { value: pane } = await $.state.get(PANE)
    if (!pane) return <Text dimColor>Run /bim-view to load a model.</Text>

    let data = loaded.get(pane.source)
    if (!data) {
      try {
        data = JSON.parse(await $.fs.read(pane.source)) as BimData
        loaded.set(pane.source, data)
      } catch {
        return <Text>Cannot read {pane.source}. Run /bim-view again.</Text>
      }
    }
    const elements = data.elements
    const set = (patch: Partial<BimPaneView>) => async () => {
      const { value: cur } = await $.state.get(PANE)
      if (cur) await $.state.set(PANE, { ...cur, ...patch })
    }
    const cats = Object.keys(categoryColors(elements)).sort()
    const counts: Record<string, number> = {}
    for (const el of elements) counts[el.category ?? 'Generic'] = (counts[el.category ?? 'Generic'] ?? 0) + 1
    const selected = pane.selected === null ? undefined : elements.find(el => String(el.id) === pane.selected)

    const columns = e.props.bodyColumns ?? e.viewport?.columns ?? 100
    const width = Math.max(320, Math.min(960, columns * 8))
    const height = Math.round(width * 0.62)
    const bounds = meshBounds(elements)
    const state = setNamedView({ ...createViewState(), aspect: width / height }, pane.view, bounds)
    state.azimuth -= (pane.turns * Math.PI) / 4
    zoomAt(state, 1 / pane.zoom, 0, 0, width / height)
    const visible = elements.filter(el => !pane.hidden.includes(el.category ?? 'Generic'))
    const title = (data.source?.title ?? 'Model') + ' · ' + visible.length + ' of ' + elements.length + ' elements'

    const views: [BimPaneView['view'], string][] = [['top', 'Top'], ['front', 'Front'], ['right', 'Right'], ['perspective', 'Persp']]
    const controls = (
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        {views.map(([v, label]) => (
          <Button key={'v-' + v} label={label} variant={pane.view === v ? 'primary' : 'secondary'} onPress={set({ view: v, turns: 0 })} />
        ))}
        <Button key="rot-l" label="Rotate left" onPress={set({ turns: pane.turns - 1 })} />
        <Button key="rot-r" label="Rotate right" onPress={set({ turns: pane.turns + 1 })} />
        <Button key="zoom-in" label="Zoom in" onPress={set({ zoom: pane.zoom * 1.5 })} />
        <Button key="zoom-out" label="Zoom out" onPress={set({ zoom: pane.zoom / 1.5 })} />
        <Button key="fit" label="Zoom extents" onPress={set({ zoom: 1 })} />
        <Button key="open3d" label="Open 3D viewer" variant="primary" onPress={() => { void openInBrowserPane($, pane.htmlUrl) }} />
      </Box>
    )
    const chips = (
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        {cats.map(cat => {
          const isOn = !pane.hidden.includes(cat)
          return (
            <Button key={'cat-' + cat} label={(isOn ? 'On  ' : 'Off ') + cat + ' ' + counts[cat]} dimColor={!isOn}
              onPress={set({ hidden: isOn ? [...pane.hidden, cat] : pane.hidden.filter(c => c !== cat) })} />
          )
        })}
      </Box>
    )
    const picker = Select === undefined ? null : (
      <Select key="pick" label="Element" value={pane.selected ?? ''}
        options={[{ value: '', label: 'None' }, ...visible.slice(0, 300).map(el => ({ value: String(el.id), label: (el.category ?? '') + ' · ' + (el.name ?? '') + ' · ' + el.id }))]}
        onSelect={(value: string) => { void set({ selected: value === '' ? null : value })() }} />
    )
    const props = selected === undefined ? null : (() => {
      const b = elementBounds(selected)
      const rows: [string, string][] = [
        ['Element ID', String(selected.id)], ['Category', selected.category ?? ''], ['Family', selected.family ?? ''],
        ['Type', selected.type ?? ''], ['Level', selected.level ?? ''],
        ['Size X, Y, Z', [0, 1, 2].map(i => formatParam({ v: (b.max[i] ?? 0) - (b.min[i] ?? 0), u: 'ft' })).join(' · ')],
        ...Object.entries(selected.params ?? {}).map(([k, v]): [string, string] => [k, formatParam(v)]),
      ]
      return (
        <Box flexDirection="column">
          <Text bold>{selected.name ?? selected.category}</Text>
          {rows.filter(r => r[1] !== '').map(([k, v]) => <Text key={'p-' + k}><Text dimColor>{k}: </Text>{v}</Text>)}
        </Box>
      )
    })()

    if (e.surface === 'terminal') {
      return (
        <Box flexDirection="column" gap={1}>
          <Text bold>{title}</Text>
          <Text dimColor>This surface cannot draw pictures. Open the 3D viewer page: {pane.htmlUrl}</Text>
          {controls}
          {chips}
          {picker}
          {props}
        </Box>
      )
    }
    const { Svg } = $.ui.resolve(e)
    const drawing = renderSvg(visible, state, { width, height, selected: pane.selected, background: '#efece4' })
    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>{title}</Text>
        {controls}
        <Svg source={drawing.svg} isInteractive width={width} height={height}
          alt={'BIM view, ' + pane.view + ' view, ' + visible.length + ' elements. Hover an element to see its name and ID.'} />
        {drawing.isCut && <Text dimColor>Inline preview draws the nearest {drawing.drawn} of {drawing.total} triangles. Open the 3D viewer for the full model.</Text>}
        <Text dimColor>Hover an element for its name and ID. X red = East, Y green = North (Project North), Z blue = Up.</Text>
        {chips}
        {picker}
        {props}
      </Box>
    )
  })
}
