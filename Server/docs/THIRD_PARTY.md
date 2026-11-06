# Sources, tools and licenses

- [Next.js](https://github.com/vercel/next.js/blob/canary/license.md), [React](https://github.com/facebook/react/blob/main/LICENSE): MIT, locally installed via npm; no CDN fonts/assets.
- [TypeScript](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt): Apache-2.0, development type checking.
- [Playwright](https://github.com/microsoft/playwright/blob/main/LICENSE): Apache-2.0, development tests. Existing cached Chromium used; no browser downloaded.
- [MySqlConnector](https://github.com/mysql-net/MySqlConnector/blob/master/LICENSE): MIT. Pinned 2.6.2; the 2.5.0 TLS advisory was resolved before shipping this server.
- [Agentation](https://github.com/benjitaylor/agentation/blob/main/LICENSE): **PolyForm Shield 1.0.0**, not MIT. Explicitly requested dev annotation tool, loaded only with NODE_ENV=development, no cloud endpoint configured. The package license remains included under node_modules.
- The recognizer follows VietOCR (Apache-2.0). Its original license is retained in `worker/core/LICENSE_VietOCR.txt`; current AI-team source/config provenance is in `models/ML_s44/provenance.json`. Existing model ownership/license remains with the project and its contributors.

The dashboard layout/CSS/icons are implemented directly in this repository, with no copied commercial template. The old request for MIT styles is respected for the UI framework choice; Agentation is the explicitly named development tool exception, and is documented as such rather than relabelled MIT.

Applied plugin guidance (local-only hosting, not a Cloudflare deployment): Sites `sites/SKILL.md`; Web Data Visualization `data-visualization/SKILL.md`, `dashboards-and-real-time-visualization/SKILL.md`, `react-and-nextjs-data-visualization/SKILL.md`. Chart ownership: React-rendered SVG, truthful real snapshots, directly labelled p50/p95, responsive tables, stale/offline state and export to JSON.

Primary architecture references:

- [ASP.NET hosted background queues](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/host/hosted-services?view=aspnetcore-10.0)
- [ASP.NET rate limiting](https://learn.microsoft.com/en-us/aspnet/core/performance/rate-limit?view=aspnetcore-10.0)
- [PyTorch CUDA allocator accounting](https://docs.pytorch.org/docs/2.15/notes/cuda.html#memory-management)
- [MySqlConnector compatibility](https://mysqlconnector.net/)
- [Windows Job Objects and child containment](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [Agentation install / local-only dev integration](https://www.agentation.com/install)


## Server-only / Supabase update

MySqlConnector is removed from the runtime project. Supabase Flutter 2.18.3 / Supabase Dart / GoTrue use the MIT license (bundled dependency licenses available in the Flutter package cache and APK notices); app_links and url_launcher supply native OAuth callbacks/browser launch. The UI is still the existing custom Next/React interface; Agentation remains dev-only under its own license. No new commercial template or browser/model/SDK download was introduced.

Optional Windows integrated-GPU inference reuses [ONNX Runtime / DirectML](https://github.com/microsoft/onnxruntime/blob/main/LICENSE) (MIT). The installed runtime and verified model export stay on the server; no new client inference dependency or UI template is introduced.
