# tablet/ — station tablet

Advanced health monitoring for someone sitting down with time to read.

| File | What it is |
|---|---|
| `monitor.html` | Crew health monitor. Live from the backend only: every channel, the Checker's verdict, the "why trust this" panel, data problems, and NASA space-environment context. Shows nothing when there is no link. |
| `index.html` | Commander, CMO and My health roles. The Commander sees tier and action only; medical detail needs the CMO role or the crew member's consent. |
| `crew-console.html` | Detailed view of one crew member: Holo body, Dashboard and AR, with the decision card and advisor. |

Shared styles and components come from `../css` and `../js`.
