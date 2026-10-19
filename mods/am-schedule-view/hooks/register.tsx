// am-schedule-view mod: /am-schedule-view <file.json> opens a pane with the schedule or change preview.
// The pane is drawn with the engine's own elements (no HTML in a pane): a Markdown table, one page at a
// time, plus a filter field, schedule buttons, paging and Copy as TSV. The full interactive page
// (sort, column hide, compare, CSV) is skills/am-schedule-view/scripts/render-table.ps1.
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { AmScheduleViewCursor, AmScheduleViewModel } from '../types'
import { PAGE_SIZE, pageMarkdown, parseArgs, parseModel, toTsv } from './table'

const PANE = 'am-schedule-view'
const model = atom({ plugin: 'am-schedule-view', key: 'model' } as const, null as AmScheduleViewModel | null)
const cursor = atom({ plugin: 'am-schedule-view', key: 'cursor' } as const, { table: 0, page: 0, filter: '' } as AmScheduleViewCursor)

const USAGE =
  'Usage: /am-schedule-view <path to .json>. Give a file from the am-schedule-view skill: ' +
  'read_schedules.py output, or a change-preview file. Ask Claude "show me the door schedule" to make one.'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'am-schedule-view',
      description: 'Show a Revit schedule or a change preview (JSON from the am-schedule-view skill) in a pane',
      argumentHint: '<file.json>',
    })
    return next(e)
  })

  on('command.run', { command: 'am-schedule-view' }, async ($, e) => {
    const path = parseArgs(e.args)
    if (!path) return { text: USAGE }
    let text: string
    try {
      text = await $.fs.read(path)
    } catch {
      return { text: 'Cannot read ' + path + '. Check the path. The pane reads files up to 4 MB.' }
    }
    let m: AmScheduleViewModel
    try {
      m = parseModel(text, path)
    } catch (err) {
      return { text: 'Cannot show ' + path + ': ' + (err instanceof Error ? err.message : String(err)) }
    }
    await update($, model, () => m)
    await update($, cursor, () => ({ table: 0, page: 0, filter: '' }))
    await $.ui.open({ id: PANE, title: m.title })
    const names = m.tables.map(t => t.name + ' (' + t.sourceRows + ' rows)').join(', ')
    return {
      text: 'Opened ' + path + ' in the pane: ' + names + '.',
      context: [
        'The am-schedule-view pane shows ' + path + ' (' + m.kind + '). ' + m.facts.join(' ') +
          ' For the full interactive page, run skills/am-schedule-view/scripts/render-table.ps1 -Json <file> -Out <html>.',
      ],
    }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown } = $.ui.resolve(e)
    const m = await read($, model)
    const cur = await read($, cursor)
    if (!m || m.tables.length === 0) {
      return (
        <Box flexDirection="column">
          <Text dimColor>No table is loaded.</Text>
          <Text dimColor>{USAGE}</Text>
        </Box>
      )
    }
    const ti = Math.min(cur.table, m.tables.length - 1)
    const t = m.tables[ti]!
    const width = e.props.bodyColumns ?? 80
    const maxCell = Math.max(8, Math.min(32, Math.floor(width / Math.max(1, Math.min(t.columns.length, 8))) - 3))
    const pg = pageMarkdown(t, cur.filter, cur.page, PAGE_SIZE, maxCell)
    const setCursor = (fn: (c: AmScheduleViewCursor) => AmScheduleViewCursor) => update($, cursor, c => fn(c ?? { table: 0, page: 0, filter: '' }))

    // Input exists on the terminal and the desktop surfaces only; narrowing e.surface narrows the table.
    let filterField = null
    if (e.surface === 'terminal' || e.surface === 'desktop') {
      const { Input } = $.ui.resolve(e)
      filterField = (
        <Input
          key="filter"
          label="Filter"
          placeholder="type, then Enter"
          value={cur.filter}
          onSubmit={(v: string) => void setCursor(c => ({ ...c, filter: v, page: 0 }))}
        />
      )
    }

    return (
      <Box flexDirection="column">
        <Text bold>
          {m.title}
          {m.document ? '  /  ' + m.document : ''}
        </Text>
        {m.facts.map(f => (
          <Text dimColor={!/blocked|Preview only/.test(f)} color={/blocked/.test(f) ? 'yellow' : undefined}>
            {f}
          </Text>
        ))}
        {m.tables.length > 1 && (
          <Box flexDirection="row" flexWrap="wrap">
            {m.tables.slice(0, 12).map((x, i) => (
              <Button
                key={'table-' + i}
                label={x.name}
                variant={i === ti ? 'primary' : undefined}
                onPress={() => setCursor(() => ({ table: i, page: 0, filter: '' }))}
              />
            ))}
          </Box>
        )}
        {filterField}
        <Markdown key="table" text={pg.markdown} />
        <Box flexDirection="row">
          <Button key="prev" label="Prev" onPress={() => setCursor(c => ({ ...c, page: Math.max(0, pg.page - 1) }))} />
          <Text dimColor>
            {' '}
            Page {pg.page + 1} of {pg.pages}. {pg.matching} of {t.rows.length} rows
            {t.sourceRows > t.rows.length ? ' (first ' + t.rows.length + ' of ' + t.sourceRows + ')' : ''}.{' '}
          </Text>
          <Button key="next" label="Next" onPress={() => setCursor(c => ({ ...c, page: Math.min(pg.pages - 1, pg.page + 1) }))} />
          <Button
            key="copy"
            label="Copy as TSV"
            onPress={async press => {
              const r = await $.ui.copy({ text: toTsv(t, cur.filter), surface: press.surface })
              void $.ui.toast(r.isCopied ? 'Copied ' + pg.matching + ' rows as TSV' : 'Copy failed: ' + r.reason)
            }}
          />
        </Box>
        <Text dimColor>Source: {m.source}</Text>
      </Box>
    )
  })
}
