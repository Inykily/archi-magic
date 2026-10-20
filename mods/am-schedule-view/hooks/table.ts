// Pure helpers for the am-schedule-view mod: read the skill's JSON, page it, write Markdown and TSV.
// No `$` here, so the tests can call every function directly.
import type { AmScheduleViewModel, AmScheduleViewTable } from '../types'

/** Rows kept per table in the pane's state. The HTML page (render-table.ps1) shows all rows. */
export const ROW_CAP = 2000
export const PAGE_SIZE = 25

type Json = null | boolean | number | string | Json[] | { [k: string]: Json }

function obj(v: Json | undefined): { [k: string]: Json } | undefined {
  return v !== null && typeof v === 'object' && !Array.isArray(v) ? v : undefined
}
function arr(v: Json | undefined): Json[] {
  return Array.isArray(v) ? v : []
}
function str(v: Json | undefined): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'string' ? v : typeof v === 'object' ? JSON.stringify(v) : String(v)
}
function row(v: Json | undefined): string[] {
  return arr(v).map(str)
}

/**
 * Parses what the skill writes: read_schedules.py output (plain, its `{payload}` wrapper, or the
 * whole agent run record) or a change-preview file. Throws an Error with a plain message on bad input.
 */
export function parseModel(text: string, source: string): AmScheduleViewModel {
  let data: Json
  try {
    data = JSON.parse(text.replace(/^\uFEFF/, '')) as Json
  } catch {
    throw new Error('The file is not valid JSON.')
  }
  let o = obj(data)
  const res = obj(o?.result)
  const wrap = res && typeof res.payload === 'string' ? res : o && typeof o.payload === 'string' ? o : undefined
  if (wrap) {
    try {
      o = obj(JSON.parse(str(wrap.payload)) as Json)
    } catch {
      throw new Error('The payload in the file is not valid JSON.')
    }
  } else if (res && typeof res.kind === 'string') {
    o = res
  }
  if (!o) throw new Error('The file holds no JSON object.')
  const kind = str(o.kind) || (o.before ? 'change-preview' : o.schedules ? 'schedules' : '')
  if (kind === 'change-preview') return previewModel(o, source)
  if (kind === 'schedules') return schedulesModel(o, source)
  if (kind === 'schedule-list') return listModel(o, source)
  throw new Error('Unknown kind "' + kind + '". Expected schedules, schedule-list or change-preview.')
}

function capped(name: string, category: string, columns: string[], rows: string[][], kinds: string[]): AmScheduleViewTable {
  return { name, category, columns, rows: rows.slice(0, ROW_CAP), kinds: kinds.slice(0, ROW_CAP), sourceRows: rows.length }
}

function schedulesModel(o: { [k: string]: Json }, source: string): AmScheduleViewModel {
  const tables = arr(o.schedules).map(s => {
    const so = obj(s) ?? {}
    const rows = arr(so.rows).map(row)
    const kinds = arr(so.rowKinds).map(str)
    const keep = rows.map((_, i) => (kinds[i] ?? 'body') !== 'blank')
    return capped(
      str(so.name),
      str(so.category),
      row(so.columns),
      rows.filter((_, i) => keep[i]),
      rows.map((_, i) => kinds[i] ?? 'body').filter((_, i) => keep[i]),
    )
  })
  return { source, kind: 'schedules', title: 'Schedules', document: str(o.document), tables, facts: [] }
}

function listModel(o: { [k: string]: Json }, source: string): AmScheduleViewModel {
  const rows = arr(o.schedules).map(s => {
    const so = obj(s) ?? {}
    return [str(so.name), str(so.category), str(so.kind), str(so.rows), so.onSheet === true ? 'Yes' : 'No', arr(so.sheets).map(str).join(', ')]
  })
  const t = capped('Schedules in this model', '', ['Name', 'Category', 'Type', 'Rows', 'On sheet', 'Sheets'], rows, rows.map(() => 'body'))
  return { source, kind: 'schedule-list', title: 'Schedules in this model', document: str(o.document), tables: [t], facts: [] }
}

/** One table of the changed, added, removed and flagged rows; changed cells read "old -> new". */
function previewModel(o: { [k: string]: Json }, source: string): AmScheduleViewModel {
  const columns = row(o.columns)
  const k = Math.max(0, columns.indexOf(str(o.keyColumn)))
  const before = arr(o.before).map(row)
  const after = arr(o.after).map(row)
  const warn = new Map<string, string[]>()
  for (const w of arr(o.warnings)) {
    const wo = obj(w) ?? {}
    const key = str(wo.row)
    warn.set(key, [...(warn.get(key) ?? []), str(wo.text)])
  }
  const bmap = new Map(before.map(r => [r[k] ?? '', r] as const))
  const amap = new Map(after.map(r => [r[k] ?? '', r] as const))
  const keys = [...new Set([...before.map(r => r[k] ?? ''), ...after.map(r => r[k] ?? '')])]
  const counts = { changed: 0, unchanged: 0, added: 0, removed: 0 }
  const recs: { sortKey: string; cells: string[] }[] = []
  const sortCol = Math.max(0, columns.indexOf(str(arr(o.changedColumns)[0])))
  for (const key of keys) {
    const b = bmap.get(key)
    const a = amap.get(key)
    let status: keyof typeof counts
    if (!b) status = 'added'
    else if (!a) status = 'removed'
    else status = columns.some((_, c) => (b[c] ?? '') !== (a[c] ?? '')) ? 'changed' : 'unchanged'
    counts[status]++
    const w = warn.get(key)
    if (status === 'unchanged' && !w) continue
    const cells = columns.map((_, c) => {
      const bv = b?.[c] ?? ''
      const av = a?.[c] ?? ''
      return status === 'changed' && bv !== av ? bv + ' -> ' + av : a ? av : bv
    })
    recs.push({ sortKey: (a ?? b ?? [])[sortCol] ?? '', cells: [status + (w ? ' (!)' : ''), ...cells] })
  }
  const coll = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' })
  recs.sort((x, y) => coll.compare(x.sortKey, y.sortKey))
  const facts = [
    'Preview only. Nothing in Revit has changed yet.',
    counts.changed + ' changed, ' + counts.unchanged + ' unchanged, ' + counts.added + ' added, ' + counts.removed + ' removed, ' + arr(o.warnings).length + ' warnings.',
  ]
  if (o.blocked === true) facts.push('Apply is blocked: resolve warnings first.')
  const params = obj(o.params)
  if (params) facts.push('Interpreted as: ' + Object.keys(params).map(p => p + ': ' + str(params[p])).join(', '))
  for (const [key, texts] of warn) for (const t of texts) facts.push('Warning ' + key + ': ' + t)
  for (const n of arr(o.notes)) facts.push('Note: ' + str(n))
  const t = capped('Changes', '', ['Change', ...columns], recs.map(r => r.cells), recs.map(() => 'body'))
  return { source, kind: 'change-preview', title: str(o.title) || 'Change preview', document: '', tables: [t], facts }
}

/** Indexes of the rows a filter keeps (case-insensitive, any cell). */
export function filteredRows(t: AmScheduleViewTable, filter: string): number[] {
  const f = filter.trim().toLowerCase()
  const out: number[] = []
  t.rows.forEach((r, i) => {
    if (!f || r.join('\u0001').toLowerCase().includes(f)) out.push(i)
  })
  return out
}

function mdCell(s: string, max: number): string {
  let v = s.replace(/\|/g, '\\|').replace(/[\r\n\t]+/g, ' ').trim()
  if (v.length > max) v = v.slice(0, max - 1) + '...'
  return v === '' ? ' ' : v
}

/** One page of the table as a Markdown table; group rows in bold caps, total rows in bold. */
export function pageMarkdown(t: AmScheduleViewTable, filter: string, page: number, pageSize = PAGE_SIZE, maxCell = 28) {
  const idx = filteredRows(t, filter)
  const pages = Math.max(1, Math.ceil(idx.length / pageSize))
  const p = Math.min(Math.max(0, page), pages - 1)
  const slice = idx.slice(p * pageSize, (p + 1) * pageSize)
  const cols = t.columns.length > 0 ? t.columns : ['(no columns)']
  const lines = [
    '| ' + cols.map(c => mdCell(c, maxCell)).join(' | ') + ' |',
    '| ' + cols.map(() => '---').join(' | ') + ' |',
  ]
  for (const i of slice) {
    const r = t.rows[i] ?? []
    const kind = t.kinds[i] ?? 'body'
    if (kind === 'group') {
      const label = r.filter(Boolean).join(' ')
      lines.push('| **' + mdCell(label.toUpperCase(), 60) + '** |' + ' |'.repeat(Math.max(0, cols.length - 1)))
      continue
    }
    const cells = cols.map((_, c) => mdCell(r[c] ?? '', maxCell))
    lines.push('| ' + (kind === 'total' ? cells.map(c => (c.trim() ? '**' + c + '**' : c)) : cells).join(' | ') + ' |')
  }
  if (slice.length === 0) lines.push('| _No rows match._ |' + ' |'.repeat(Math.max(0, cols.length - 1)))
  return { markdown: lines.join('\n'), page: p, pages, shown: slice.length, matching: idx.length }
}

/** The filtered rows as TSV with a heading row: what "Copy as TSV" puts on the clipboard. */
export function toTsv(t: AmScheduleViewTable, filter: string): string {
  const cell = (s: string) => s.replace(/[\t\r\n]+/g, ' ')
  const out = [t.columns.map(cell).join('\t')]
  for (const i of filteredRows(t, filter)) out.push((t.rows[i] ?? []).map(cell).join('\t'))
  return out.join('\n')
}

/** Splits the command's argument: a path, quoted or not. */
export function parseArgs(args: string): string {
  const s = args.trim()
  const m = /^"([^"]+)"|^'([^']+)'/.exec(s)
  if (m) return (m[1] ?? m[2] ?? '').trim()
  return s
}
