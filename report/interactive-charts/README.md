# Interactive chart acceptance

Both equity and dataset charts now offer nearest-recorded-point inspection, dotted crosshairs, solid markers, explicit values and labelled deltas, plus an enlarged native dialog. Dataset previews are taller. UTC, units, downsampling and sealed HOLDOUT remain explicit.

26 frontend tests passed. Production build, formatting and protected-file check passed. Read-only Chrome checks passed against real local API records, including keyboard, focus restoration, touch, narrow screens and light/dark themes. No backend, eval or stored research results changed.

The equity boundary date is labelled IS/OOS boundary day because intraday split days can contain both scopes.

See [browser proof](proof.json), [expanded dataset](dataset-expanded.png), [equity hover](equity-hover.png), and [mobile light theme](mobile-light-expanded.png). Run `node scripts/verify_charts.mjs` to repeat the browser checks.
