import { test, expect } from 'claude-code/testing'

import { fileUrl, parseArgs } from './register'

const TEMPLATE = '<title>__TITLE__</title><script>/*__CORE__*/\nconst DATA = /*__DATA__*/null;</script>'
const CORE = 'export const WORLD_UP = [0, 0, 1];'
const RUN = { origin: { kind: 'composer' as const }, presentation: { isFullscreen: false, columns: 80 } }
const DEMO = JSON.stringify({
  source: { title: 'Demo' },
  elements: [{ id: 1, category: 'Walls', mesh: { vertices: [0, 0, 0, 1, 0, 0, 0, 1, 0], indices: [0, 1, 2] } }],
})

test('parseArgs reads a path and --open', () => {
  expect(parseArgs('')).toEqual({ input: undefined, isOpen: false })
  expect(parseArgs('"C:/My Models/a.json" --open')).toEqual({ input: 'C:/My Models/a.json', isOpen: true })
})

test('fileUrl makes a file URL from a Windows path', () => {
  expect(fileUrl('C:\\Temp\\a b.html')).toBe('file:///C:/Temp/a%20b.html')
})

test('/bim-view with no path builds the demo page next to demo.json', async ($, on) => {
  const written: { path: string; text: string }[] = []
  on('session.cwd', () => ({ value: 'C:/proj' }))
  on('fs.read', ($, e) => {
    if (e.path.endsWith('demo.json')) return { value: DEMO }
    if (e.path.endsWith('template.html')) return { value: TEMPLATE }
    if (e.path.endsWith('viewer-core.mjs')) return { value: CORE }
    throw new Error('unexpected read ' + e.path)
  })
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('mcp.call', () => ({ value: { content: [], isError: true } }))
  on('fs.write', ($, e) => {
    written.push({ path: e.path, text: e.text })
    return { value: undefined }
  })
  const result = await $.command.run({ ...RUN, command: 'bim-view', args: '' })
  expect(result.text).toContain('BIM view: 1 elements. Viewer page:')
  expect(result.text).toContain('demo.viewer.html')
  expect(written.length).toBe(1)
  expect((written[0]?.path ?? '').split(String.fromCharCode(92)).join('/')).toContain('/viewer/demo.viewer.html')
  expect(written[0]?.text).toContain('const WORLD_UP = [0, 0, 1];')
  expect(written[0]?.text).toContain('"category":"Walls"')
  expect(written[0]?.text).toContain('<title>Demo</title>')
})

test('/bim-view reports a JSON file it cannot read', async ($, on) => {
  on('session.cwd', () => ({ value: 'C:/proj' }))
  on('fs.read', () => {
    throw new Error('ENOENT')
  })
  const result = await $.command.run({ ...RUN, command: 'bim-view', args: 'missing.json' })
  expect(result.text).toContain('Cannot read the BIM JSON')
})

const PANE_PROPS = {
  title: 'BIM view', isFocused: false, bodyColumns: 100, placement: 'dock',
  scroll: { top: 0, bodyRows: 40 }, view: {},
} as unknown as Parameters<typeof JSON.stringify>[0]

test('/bim-view opens the inline pane: an SVG drawing on desktop, text on the terminal, buttons change the view', async ($, on) => {
  on('session.cwd', () => ({ value: 'C:/proj' }))
  on('fs.read', ($, e) => {
    if (e.path.endsWith('demo.json')) return { value: DEMO }
    if (e.path.endsWith('template.html')) return { value: TEMPLATE }
    if (e.path.endsWith('viewer-core.mjs')) return { value: CORE }
    throw new Error('unexpected read ' + e.path)
  })
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('mcp.call', () => ({ value: { content: [], isError: true } }))
  await $.command.run({ ...RUN, command: 'bim-view', args: '' })

  const desk = await $.ui.mount({ plugin: 'am-bim-viewer', surface: 'desktop', component: 'Pane', requestId: 'am-bim-view', props: PANE_PROPS as never })
  const svg = await desk.find({ type: 'Svg' })
  expect(svg).toBeDefined()
  await desk.press({ key: 'v-top' })
  const topBtn = await desk.find({ key: 'v-top' })
  expect(JSON.stringify(topBtn)).toContain('primary')
  await desk.press({ key: 'cat-Walls' })
  expect(await desk.find({ type: 'Button', text: /Off Walls/ })).toBeDefined()
  await desk.unmount()

  const term = await $.ui.mount({ plugin: 'am-bim-viewer', surface: 'terminal', component: 'Pane', requestId: 'am-bim-view', props: PANE_PROPS as never })
  expect(await term.find({ type: 'Text', text: /cannot draw pictures/ })).toBeDefined()
  await term.unmount()
})
