# tablet/ — station tablet

Advanced health monitoring for someone sitting down with time to read.

| File | What it is |
|---|---|
| `monitor.html` | Crew health monitor. Live from the backend only: every channel, the Checker's verdict, the "why trust this" panel, data problems, and NASA space-environment context. Shows nothing when there is no link. |
| `index.html` | Retired. An earlier role-based tablet (Commander / CMO / My health) that displayed scripted demo crew as if live and the roles were a page toggle only. It now shows a notice pointing to `monitor.html`; the old page is in git history. |
| `crew-console.html` | Retired. An earlier detailed crew view with the same scripted demo data; now a notice pointing to `monitor.html`. |

Shared styles and components come from `../css` and `../js`.
