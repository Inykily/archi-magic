// am-bim-viewer mod.
//
// A pane cannot run WebGL: pane elements are Box/Text/Button-style trees, the
// desktop Svg element is script-less, and a Client surface module draws only
// character-cell elements. So the mod's surface is a slash command that writes
// a self-contained HTML viewer page and hands its file URL to the model, which
// opens it in the app's Browser pane (or the person opens it in a browser).
import type { Register } from 'claude-code'

import { buildViewerHtml } from '../viewer/build.mjs'

const COMMAND = 'bim-view'

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
  return dir.replace(/[\\/]+$/, '') + '/' + file
}

export function fileUrl(path: string): string {
  const p = path.replace(/\\/g, '/')
  return 'file://' + (p.startsWith('/') ? '' : '/') + encodeURI(p).replace(/#/g, '%23')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: 'Build a 3D BIM viewer page from a JSON export (no path: demo model)',
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

    let data: unknown
    try {
      data = JSON.parse(await $.fs.read(source))
    } catch (err) {
      const why = err instanceof Error ? err.message : String(err)
      return { text: 'Cannot read the BIM JSON at ' + source + '. ' + why + ' (Files over 4 MiB cannot be read by the mod: use skills/am-bim-viewer/scripts/build-viewer.mjs with node.)' }
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

    const count = (data as { elements: unknown[] }).elements.length
    const url = fileUrl(output)
    let opened = ''
    if (isOpen) {
      const isWindows = (await $.env.get('OS')) === 'Windows_NT'
      const ran = await $.process.run(isWindows ? ['explorer.exe', output] : ['open', output]).catch(() => undefined)
      // explorer.exe returns exit code 1 even on success; only a failure to start is a failure.
      opened = ran === undefined ? ' Could not start the default browser.' : ' Opened in the default browser.'
    }
    $.ui.toast('BIM viewer ready: ' + count + ' elements')
    return {
      text: 'BIM viewer page: ' + output + ' (' + count + ' elements).' + opened,
      context: [
        'The am-bim-viewer page is at ' + url + ' . If a Browser pane tool is available, open that file URL there so the person can see the 3D model; otherwise give them the path. Controls: right drag rotate (perspective) or pan (Top/Front/Right), Shift+right drag pan, Ctrl+right drag zoom, wheel zoom at cursor, left click select.',
      ],
    }
  }).catch(($, e, next) =>
    next.called ? next(e) : { text: 'The /bim-view command failed: ' + String(next.error?.message ?? next.error?.kind ?? 'unknown error') },
  )
}
