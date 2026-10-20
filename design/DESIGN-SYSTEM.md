# archi-magic design system: "Visual Research"

Every archi-magic page uses this system: the 3D viewer, the schedule and markup tables, the change preview, and the model-health dashboard. It comes from a monochrome poster study: a soft beam of light, film grain, 1 px construction geometry, and small monospace type. It reads like an architect's drawing, not like software.

The tokens live in `design/tokens.css`. That file is the only source. `scripts/sync-design-tokens.ps1` copies it into each page template between the `am-tokens:start` and `am-tokens:end` markers, and `check-skills.ps1` fails if any copy drifts.

## Principles

1. **Value, not hue.** Use only black, white and grays (`--v0` to `--v7`). Do not use brand color, and do not encode meaning with color.
2. **One focal dot.** Each view has at most one solid dot (`.am-dot`). It marks the one thing that matters most: the selected element, the current item, or a blocking problem.
3. **Light is the material.** Backgrounds are a soft vertical beam (`--beam`) inside a vignette (`--vignette`), with fine grain over everything (`.am-surface::after`). Do not use flat fills or drop shadows.
4. **Construction lines, not boxes.** Draw structure with 1 px hairlines (`--line`). Use circles, axes and tangents for empty states, loaders and dividers. Rectangles have square corners. Round things are fully round.
5. **Monospace only, quiet hierarchy.** Use one family (IBM Plex Mono). Rank by tone: primary in `--ink`, secondary in `--ink-2`. Use size only for the single lead line. Labels are lowercase. Section headers are uppercase micro text, tracked (`.am-micro`), with an index such as `13 / 30` (`.am-index`).
6. **Axis and air.** Compose along a centered vertical axis where the layout allows it. Leave generous empty space. Put fewer things on screen.
7. **Slow and calm motion.** Use fades and eases of about 420 ms (`--slow`, `--ease`). Do not bounce.

## Tokens (summary)

| Token | Value | Use |
|---|---|---|
| `--v0` / `--v7` | `#0a0a0a` / `#f4f4f1` | ink / paper |
| `--ink`, `--ink-2`, `--ink-3` | theme-dependent | primary, secondary, tertiary text |
| `--line`, `--line-strong` | ink at 14% / 42% | hairlines, construction geometry |
| `--beam`, `--vignette` | radial gradients | the light column and the dark edge |
| `--grain`, `--grain-opacity` | SVG fractal noise, 0.07 (paper) / 0.11 (night) | texture over the whole page |
| `--font` | IBM Plex Mono 300/400/500 | all text |
| `--fs-micro`, `--fs-body`, `--fs-lead` | 10.5 / 12.5 / 14 px | label, body, the one lead line |
| `--radius`, `--round` | 0 / 999px | square rectangles, fully round dots and rings |

Themes: **paper** for tables and dashboards; **night** (`.am-night`) for the 3D viewport. Night is also the default for every page when the OS is in dark mode.

## Functional states without color

| State | Mark |
|---|---|
| ok | hollow ring (`.am-status`) |
| warning | half-filled ring (`.am-status.warn`) |
| problem / blocked | solid dot (`.am-status.bad`); a blocking banner is shown inverted (ink background, paper text) |
| selected (3D) | the element turns pure paper on the night scene with an ink hairline outline; one dot marks its label |
| changed (preview) | old value in `--ink-3` with a hairline strike, new value in `--ink` |
| hover | the hairline goes from `--line` to `--line-strong` |

3D categories use value steps (`--v2` to `--v6`), not hue. A category is told apart by its value and its name in the legend.

## Do and don't

- Do: square tables with hairline rules, a micro uppercase header with an index (`schedules  04 / 40`), and lowercase labels.
- Do: an empty state drawn as two tangent hairline circles with a dot where they meet, plus one lowercase line ("click an element / to see its data").
- Don't: colored chips, colored status pills, `border-left` accent bars, gradients with hue, rounded cards, shadows, emoji.

## Accessibility

- Text contrast (measured with the WCAG formula): `--ink` on paper is 17.97:1. `--ink-2` on paper is 4.85:1 and on night 7.01:1, so both pass AA for body text. `--ink-3` is 2.56:1 on paper and 3.70:1 on night, which is below AA. Use `--ink-3` only for supplementary marks that repeat information shown elsewhere (units, the struck-out old value next to the new value, counts in chips). Never use it for text the user must read.
- Status is never shown by tone alone. Each status has a shape (ring, half, dot) and a text label.
- Grain sits at or below 0.11 opacity, has `pointer-events: none`, and never covers text contrast.
