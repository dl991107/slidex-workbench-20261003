# Slidex workbench implementation plan

Goal: user-operated local Mac image-analysis workbench around existing Slidex 0.6.28.
Prompt diagnosis: scope clarified by user to a general standalone tool, not a particular website. No browser automation/remote target integration in this build.
Approved UI route: select image, optional piece, run Slidex, display location and raw metrics, export JSON. User requested installing the previously proposed local interface.
Architecture: Python standard-library loopback HTTP server, static HTML/CSS/JS, subprocess inference with hard timeout, existing isolated Python environment. Mac .app launcher. No cloud service or persistence of input images.
Files: outputs/Slidex工作台.app/Contents/Resources/{server.py,infer.py,web/index.html,web/app.js,web/style.css}; Contents/MacOS/launch; Contents/Info.plist. Tests in work/workbench-tests.
Budget: <=700 source lines, <=250 test lines; reuse current installed Slidex, add Pillow for header/decompression validation. No service abstraction or cloud deployment.

Tasks:
- [ ] Backend: loopback-only binding, Host/Origin/session-token validation, 12 MiB request cap, 8 MiB and 12 MP per image, strict JSON fields, PNG/JPEG/WebP validation, no raw exception exposure, single-flight inference, subprocess timeout, explicit shutdown.
- [ ] UI: native-looking light utility, system fonts, high-contrast blue actions, keyboard-accessible image upload, clear busy/empty/error/result states, no automatic recognition on upload, a result is a candidate not website acceptance, user-triggered JSON download.
- [ ] Tests: real HTTP entry for auth/invalid input/oversize/parallel contention/duplicate pure requests/timeout recovery/field allowlist, actual public independent image recognition, browser UI upload/analyze/export, mobile layout.
- [ ] Packaging: .app and Chinese quickstart, verify compiled source/dependencies/launch status, install exact new app path without overwrite, show local UI.
- [ ] Removal review and report actual checks plus remaining limitations.

Interface for UI:
GET / -> HTML with <meta name="workbench-token" content="__TOKEN__"> replaced by server.
GET /api/status -> {version:"0.6.28", backend:"基础识别", busy:boolean} (same local origin).
POST /api/analyze requires Origin=http://127.0.0.1:PORT and X-Workbench-Token from meta.
JSON {image:base64_string,piece:base64_string|null}; success HTTP 200 {ok:true,result:{success,gap_x,gap_box,confidence,method,elapsed_ms,image_width,image_height},notice:string}.
Validation/inference errors {ok:false,error:{code,message}} with 400/403/409/413/422/504/500.
POST /api/shutdown same auth, JSON {}, 200 {ok:true}.
No file paths, remote URLs, credentials, auto-browser actions or raw error strings accepted.

Boundary matrix before validation:
Null/invalid: not passed until HTTP tests. Duplicates: pure computation, test repeated request returns equivalent fields. Concurrency: not passed until second request returns busy. Permissions: not passed until Host/Origin/token tests. Timeout/errors: not passed until worker timeout and follow-up request recovery. Leakage: not passed until response whitelist/error masking assertions. Persistence: not applicable, no uploaded image storage; export user initiated in browser.

Delegation: UI owns only web files (bounded mechanical task, Luna worker, 5-8 min, no real accounts; acceptance browser checks by parent). Test worker owns only work/workbench-tests/test_server.py (Luna worker, 5-8 min, localhost generated data only; parent reruns pytest). No shared-file edits. Parent owns backend/packaging/review, avoiding duplicate work and extra model calls.
