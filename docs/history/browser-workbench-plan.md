# Browser-connected Slidex workbench

Prompt diagnosis: corrected and approved. User selected an already-open Chrome for Testing and explicitly requires all connection and execution clicks to be theirs. The agent will not connect to that browser or run a challenge. The previous image-only UI is not the requested delivery.

Goal: install a local Mac app whose user can connect a loopback CDP endpoint, select an existing tab, perform one Slidex attempt, stop it, and export a minimal result; expose the same session-authenticated local API to other software.
Architecture: existing stdlib HTTP server and bundled Python; browser_bridge.py validates discovery and owns one cancellable subprocess; browser_task.py reuses Slidex provider methods and attaches only to the selected target. No navigation, new tabs, browser shutdown, cookie export, persistent input/response logs, or automatic retry. Built-in adapters are aliyun-nocaptcha and geetest. Unsupported pages stop before input.
Budget: up to 850 added/changed production lines, tests about 300 lines. Reuse current Slidex 0.6.28 and Playwright dependencies. Files: Resources/{server.py,browser_bridge.py,browser_task.py,web/*}; work/package_workbench.py; Chinese guide and API guide in outputs.

API: POST /api/browser/connect {endpoint}; response {ok,targets:[{id,title,url}],message}. Only http://127.0.0.1:PORT or localhost accepted; discovery has a 1 MiB limit and no redirects/proxies. UI URL omits path/query/fragment. IDs are opaque session handles binding endpoint/browser websocket/target/full URL.
POST /api/browser/run {target,request_id}: user action, exactly one attempt, idempotent result cache for 64 IDs. Result whitelist {status,provider,elapsed_ms,message}, status passed/failed/unknown/unsupported/cancelled. Passed means adapter received a success response, not proof of login. 50s subprocess ceiling plus bounded cleanup; same target and URL checked again before movement. POST /api/browser/cancel {request_id} only affects matching active operation; graceful SIGTERM requests mouse-up cleanup, hard stop if necessary. No background scheduling.

Tasks:
- [x] Validate endpoint, discovery identity, opaque handles, replay and single-flight boundaries.
- [x] Implement bounded child adapter execution and cancellation cleanup.
- [x] Integrate authenticated HTTP entry and user-click UI.
- [x] Run local boundary checks and static UI checks; no live browser/challenge execution by the agent.
- [x] Package and install a new exact application path, launch only with --no-open for local startup check, provide user launch link.
- [x] Remove redundant branches and verify preserved file/import/API contracts before any removal.

Boundary evidence required: null/invalid HTTP fields; repeated request ID (same payload replay, different payload reject); concurrent execution busy; session auth + target identity and URL validation; process timeout/cancel recovery; output and exception masking. Agent live website validation intentionally unperformed by user request. No image, cookies or response persistence; only chosen user JSON export.

Delegation: Luna UI worker owns web files only (6–10m, node --check, no account access). Explorer owns read-only Slidex source review (3–5m, line evidence). Luna test worker owns new bridge tests only (5–8m, pytest with fake discovery/runner, no live CDP). Parent owns bridge/task/server/packaging and independently reruns checks. This avoids overlapping edits and extra model changes.

Final evidence (2026-10-03 Asia/Shanghai): 63 Python checks passed; expected Pillow oversized-image warning occurred in a rejection test. Node UI-state check and syntax check passed. Installed exact new /Applications/Slidex工作台.app; source checksums matched. Installed bundled runtime resolved within that app. Its launcher with --no-open served /, /app.js, /style.css and /api/status, then authenticated shutdown exited 0. No browser connection/run route was called against a real CDP endpoint.

Boundary matrix: null/invalid—tested through HTTP and bridge; repeats—tested exact request replay and cross-target conflict; concurrency—tested busy and cancellation ownership; auth/identity—tested Host/Origin/token, opaque handles and changed URL/browser; timeout—tested drip-feed deadline and exited parent with live child pipes; errors/data—tested sanitized output whitelist and no raw exception response; browser ownership—source reviewed (no navigation/new-page/close/cookie calls), live lifecycle intentionally untested per user request.

Removal review: reused existing HTTP auth, response structure, launcher and bundled dependencies; removed a redundant title from worker input and unused import; kept existing image API/infer entry because their documented test/import contracts still exist. No additional framework, service manager, login item or browser restart was added.
