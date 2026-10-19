export type BimPaneView = {
  source: string
  htmlUrl: string
  view: 'top' | 'front' | 'right' | 'perspective'
  turns: number
  zoom: number
  hidden: string[]
  selected: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'am-bim-viewer': { pane: BimPaneView }
  }
}
