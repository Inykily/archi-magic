import { expect, test } from 'claude-code/testing'

import { pageMarkdown, parseArgs, parseModel, toTsv } from '../hooks/table'

// A cut-down copy of a real read_schedules.py result (Snowdon Towers, Room Finish Schedule).
const SCHEDULES = {
  kind: 'schedules',
  document: 'Snowdon Towers Sample Architectural',
  schedules: [
    {
      name: 'Room Finish Schedule',
      category: 'Rooms',
      columns: ['Room Number', 'Room Name', 'Area', 'Floor Finish'],
      rows: [
        ['', '', '', ''],
        ['Parking', '', '', ''],
        ['P01', 'Parking Garage', '10307 SF', 'Concrete'],
        ['P02', 'Machine RM', '59 SF', 'Concrete'],
        ['Parking: 2', '', '10366 SF', ''],
        ['Grand total: 2', '', '10366 SF', ''],
      ],
      rowKinds: ['blank', 'group', 'body', 'body', 'total', 'total'],
    },
  ],
}

const PREVIEW = {
  kind: 'change-preview',
  title: 'Shift sheets A301+ up by one',
  keyColumn: 'ElementId',
  columns: ['ElementId', 'Sheet Number', 'Sheet Name'],
  changedColumns: ['Sheet Number'],
  before: [[1, 'A302', 'Wall Sections'], [2, 'A301', 'Building Sections'], [3, 'A101', 'Plan']],
  after: [[1, 'A303', 'Wall Sections'], [2, 'A302', 'Building Sections'], [3, 'A101', 'Plan']],
  warnings: [{ row: '3', text: 'check the issued set' }],
  blocked: true,
  params: { start: 'A301', step: 1 },
  steps: [[1, 'A302', 'A303']],
  somethingNew: { ignored: true },
}

test('reads schedule JSON, the payload wrapper and the run record alike', async () => {
  const plain = parseModel(JSON.stringify(SCHEDULES), 'a.json')
  const wrapped = parseModel(JSON.stringify({ kind: 'schedules', payloadFormat: 'ascii-json', payload: JSON.stringify(SCHEDULES) }), 'b.json')
  const record = parseModel(JSON.stringify({ status: 'ok', result: { payload: JSON.stringify(SCHEDULES) } }), 'c.json')
  for (const m of [plain, wrapped, record]) {
    expect(m.kind).toBe('schedules')
    expect(m.tables[0]?.name).toBe('Room Finish Schedule')
    // the blank row is dropped, group and total rows stay
    expect(m.tables[0]?.kinds).toEqual(['group', 'body', 'body', 'total', 'total'])
  }
})

test('rejects bad input with a plain message', async () => {
  expect(() => parseModel('{not json', 'x.json')).toThrow('not valid JSON')
  expect(() => parseModel(JSON.stringify({ kind: 'spreadsheet' }), 'x.json')).toThrow('Unknown kind')
})

test('a page is a Markdown table with styled group and total rows', async () => {
  const t = parseModel(JSON.stringify(SCHEDULES), 'a.json').tables[0]!
  const pg = pageMarkdown(t, '', 0)
  const lines = pg.markdown.split('\n')
  expect(lines[0]).toBe('| Room Number | Room Name | Area | Floor Finish |')
  expect(lines[2]).toBe('| **PARKING** | | | |')
  expect(lines[3]).toBe('| P01 | Parking Garage | 10307 SF | Concrete |')
  expect(lines[5]).toBe('| **Parking: 2** |   | **10366 SF** |   |')
  expect(pg.pages).toBe(1)
})

test('filter and paging', async () => {
  const t = parseModel(JSON.stringify(SCHEDULES), 'a.json').tables[0]!
  expect(pageMarkdown(t, 'machine', 0).matching).toBe(1)
  expect(pageMarkdown(t, 'zzz', 0).markdown).toContain('No rows match')
  const two = pageMarkdown(t, '', 9, 2)
  expect(two.pages).toBe(3)
  expect(two.page).toBe(2)
})

test('Copy as TSV gives the heading row and the filtered rows', async () => {
  const t = parseModel(JSON.stringify(SCHEDULES), 'a.json').tables[0]!
  expect(toTsv(t, 'garage')).toBe('Room Number\tRoom Name\tArea\tFloor Finish\nP01\tParking Garage\t10307 SF\tConcrete')
})

test('change preview: old -> new, warning rows kept, unknown keys ignored', async () => {
  const m = parseModel(JSON.stringify(PREVIEW), 'p.json')
  expect(m.kind).toBe('change-preview')
  const t = m.tables[0]!
  expect(t.columns).toEqual(['Change', 'ElementId', 'Sheet Number', 'Sheet Name'])
  // sorted by the new value of the first changed column; the unchanged row stays for its warning
  expect(t.rows).toEqual([
    ['unchanged (!)', '3', 'A101', 'Plan'],
    ['changed', '2', 'A301 -> A302', 'Building Sections'],
    ['changed', '1', 'A302 -> A303', 'Wall Sections'],
  ])
  expect(m.facts).toContain('Preview only. Nothing in Revit has changed yet.')
  expect(m.facts).toContain('2 changed, 1 unchanged, 0 added, 0 removed, 1 warnings.')
  expect(m.facts).toContain('Apply is blocked: resolve warnings first.')
  expect(m.facts).toContain('Interpreted as: start: A301, step: 1')
})

test('the command argument may be quoted', async () => {
  expect(parseArgs('  "C:\\a b\\x.json" ')).toBe('C:\\a b\\x.json')
  expect(parseArgs('C:\\x.json')).toBe('C:\\x.json')
  expect(parseArgs('')).toBe('')
})

test('the pane draws a hint while nothing is loaded, on every surface', async $ => {
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'am-schedule-view',
      surface,
      component: 'Pane',
      requestId: 'am-schedule-view',
      props: { title: 'Schedules', isFocused: false, bodyColumns: 100, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
    })
    expect(await ui.find({ type: 'Text', text: /No table is loaded/ })).toBeDefined()
    await ui.unmount()
  }
})
