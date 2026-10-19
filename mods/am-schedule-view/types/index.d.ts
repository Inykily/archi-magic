/** One table the pane can show: a schedule, or the rows of a change preview. */
export type AmScheduleViewTable = {
  name: string
  category: string
  columns: string[]
  rows: string[][]
  /** body | group | total | blank, one per row */
  kinds: string[]
  /** Rows in the source before the pane's cap. */
  sourceRows: number
}

/** What /am-schedule-view loaded, ready to draw. */
export type AmScheduleViewModel = {
  source: string
  kind: 'schedules' | 'schedule-list' | 'change-preview'
  title: string
  document: string
  tables: AmScheduleViewTable[]
  /** Counts and status lines for a change preview; empty for schedules. */
  facts: string[]
}

/** Where the person is in the pane. */
export type AmScheduleViewCursor = { table: number; page: number; filter: string }

declare module 'claude-code' {
  interface PluginState {
    'am-schedule-view': {
      model: AmScheduleViewModel | null
      cursor: AmScheduleViewCursor
    }
  }
}
