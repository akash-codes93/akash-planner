# Workmap Frontend

React 19 + Vite single-page UI. One file (`src/App.jsx`) renders the entire screen — task list, capture input, tag filters, detail panel, AI planner, and streak heatmap.

## Scripts

```bash
npm run dev       # Dev server with HMR (port 5173)
npm run build     # Production build to dist/
npm run lint      # ESLint checks
```

## Key Files

| File | Role |
|---|---|
| `src/App.jsx` | All components inline — no external UI library |
| `src/App.css` | All styles — no CSS framework |
| `src/AiPlanner.jsx` | Chat widget for AI planner |
| `public/favicon.svg` | Purple sparkle logo (source of truth for app icon) |

## Conventions

- No router, no sidebar, no multi-page navigation
- Tasks have only two statuses: `backlog` and `done`
- All interactions (check, expand, edit, add subtag, add tag) happen inline on the row
- Tags are right-aligned on each task row, showing 2 max with +N overflow
