# Arena interface

Run the FastAPI service at `127.0.0.1:8000`, then from this directory:

```sh
npm ci --legacy-peer-deps
npm run dev
```

Vite proxies `/api` to the local API. Open `http://127.0.0.1:5173`.
`npm run build` checks TypeScript and builds the interface; `npm test` runs the
frontend behavior tests. The root browser proof uses Playwright against the live
service. This app is local and single-user; it does not place orders.

All network access is centralized in `src/api.ts`. Page state is separate from
shared evidence components. `src/tokens.css` owns the visual tokens, with the
owner's mockup boards taking precedence over generic token defaults. Dark is
the default; theme and the three supplied accents persist in local storage.

Routes: `/new`, `/runs`, `/runs/:runId`, `/leaderboard`, `/variants/:variantId`,
`/graveyard`, `/evals`, `/data`. `?include_voided=true` is an explicit audit view.
PDF submission starts the actual pipeline. Other unimplemented writes stay
disabled. Screens use only API evidence; no mockup financial values are copied.
