# MEOW Cloud Migration Plan

Status: planning and safe foundation only. The production application has not yet been migrated or deployed.

## Goals

- Run MEOW's cloud-capable assistant backend continuously on a free-tier VPS.
- Provide authenticated web and mobile access.
- Keep the existing Windows desktop companion available as an optional future local companion; do not require it for cloud chat, memory, tasks, knowledge retrieval, or cloud-safe agents.
- Preserve the current feature set by separating cloud-capable features from hardware-bound Windows features rather than deleting them.
- Keep the existing `main` branch unchanged while migration work is developed and tested here.

## Repository findings

The current application is a Windows-first desktop assistant:
- `companion.py` starts PySide6, the mascot, voice thread, Flask on port 5005, and FastAPI on port 8000.
- `app.py` contains the existing Flask dashboard and many routes, but several routes and state snapshots assume Windows APIs, a local webcam, audio devices, or a running mascot.
- `server.py` already contains a FastAPI REST/WebSocket API and has a standalone mode, making it the best starting point for a cloud API. However, it is not production-safe as-is.
- `templates/index.html` and `templates/mobile.html` are existing UI assets to preserve and adapt, not replace.
- `memory_manager.py` stores memory, chat history, and tasks in local JSON files relative to the process working directory. Persistent mounted storage and/or a database migration are required before production.
- `requirements.txt` mixes cloud API dependencies with Windows desktop, audio, camera, local-model, and native packages. It must not be installed wholesale in a small ARM cloud VM.
- `config/settings.py` supports environment variables but also falls back to `memory.json`; production secrets must be environment-only or stored in a protected secret store.
- `server.py` has API-key checks on selected endpoints only, while other endpoints remain unauthenticated. CORS is currently wildcard. Authentication and origin policy must be fixed before public exposure.
- `tool_registry.py` includes local PC-control tools. These must be disabled in cloud mode unless a trusted local companion is connected and explicitly authorizes a command.
- The README's clone URL references a different repository name; canonical repository for this migration is `Anujpatel32/Personal-Assistant`.

## Target architecture

1. **Cloud API**: FastAPI/Uvicorn, behind Caddy or Nginx with HTTPS.
2. **Web/mobile UI**: retain current dashboard and mobile page, progressively point their API calls at the cloud API, and add PWA install support where compatible.
3. **Runtime**: Docker Compose with separate API and background-worker services; systemd/Docker restart policies for recovery.
4. **Persistence**: SQLite on a persistent VPS volume initially, with explicit backups; migrate to PostgreSQL only if concurrency/scale justifies it. Keep uploaded knowledge files on persistent storage.
5. **AI**: cloud providers only (Gemini/Groq/NVIDIA/OpenRouter according to available user keys and provider free quotas); remove local model downloads and inference from the cloud image, but retain desktop compatibility on Windows.
6. **Development**: GitHub Codespaces or another browser IDE; feature branches and pull requests; CI tests before deployment.
7. **Deployment**: GitHub Actions deploys only after tests pass and only to an explicitly configured VPS using protected secrets.

## Free VPS target

First candidate: Oracle Cloud Infrastructure Always Free Ampere A1, if the account and home-region capacity allow it. Current published allowance is 1,500 OCPU-hours and 9,000 GB-hours per month (up to 2 OCPUs and 12 GB RAM), with up to 200 GB combined block storage. Oracle documents possible idle-instance reclamation and temporary host-capacity shortages. The plan must therefore include persistent backups and a recovery procedure. Do not create paid resources or upgrade the account without explicit approval.

## Migration phases

### Phase 0 — Safety and baseline
- Keep `main` unchanged.
- Capture baseline tests and document current routes/features.
- Audit secrets, unsafe tool execution, file writes, plugin installation, CORS, and auth.
- Confirm the existing dashboard and mobile UI can work without desktop-only endpoints.

### Phase 1 — Cloud runtime
- Add a cloud-specific dependency file excluding PySide6, Windows-only packages, microphone/camera packages, and local inference.
- Add a cloud entrypoint that starts only the API and cloud-safe services; never start `companion.py` on Linux.
- Add Dockerfile, Compose, health checks, non-root runtime, persistent data mount, and reverse-proxy HTTPS configuration.
- Bind services internally; expose only HTTPS through the reverse proxy.

### Phase 2 — Security
- Require authentication for every non-health API route and WebSocket.
- Replace wildcard CORS with configured trusted origins.
- Add secure password/session or token-based user authentication, rate limits, request-size limits, secure cookies, and CSRF protection for cookie-authenticated writes.
- Store provider keys only in environment variables or encrypted settings; redact secrets from logs and API responses.
- Add a cloud tool allowlist; disable Windows/local PC-control, arbitrary file operations, code execution, and plugin installation from public cloud endpoints by default.

### Phase 3 — Persistence
- Move mutable data out of the Git checkout into a persistent data directory.
- Add atomic writes and backup/restore tests for memory, tasks, chat, settings, vector index, and uploaded documents.
- Ensure container restarts and redeploys do not erase user data.

### Phase 4 — Dashboard and mobile
- Preserve current UI templates and functionality.
- Replace LAN/local-IP assumptions with same-origin HTTPS API URLs.
- Make PC metrics, webcam, local clipboard, local media, and desktop startup controls report “requires local companion” rather than failing or pretending to run in the cloud.
- Test login, mobile layout, WebSocket reconnect, PWA install, and all cloud-capable dashboard modules.

### Phase 5 — CI/CD and operations
- Add Linux ARM64 CI in addition to existing Windows tests.
- Add dependency/security scanning, API tests, and Docker image build checks.
- Deploy by immutable image tag, run health checks, and retain rollback to the previous image.
- Add log rotation, disk-space alerts, scheduled encrypted backups, and restore drills.

### Phase 6 — Cutover
- Deploy to a free-tier VPS only after account eligibility and actual capacity are confirmed.
- Import user data with a verified backup.
- Test externally from mobile data and another network.
- Keep the PC installation untouched until cloud parity is verified; then it can be removed or retained only as an optional companion.

## Acceptance criteria

- Cloud service remains available when the user's PC is shut down.
- Authenticated web and mobile access works over HTTPS.
- No public route can execute arbitrary local PC commands, arbitrary code, or unauthenticated plugin installation.
- Existing chat, provider routing, memory, tasks, knowledge base, and cloud-safe agent features pass regression tests.
- Data survives container rebuilds and VPS restarts.
- Windows-only features are clearly marked as companion-required and are not silently removed.
- Backup restore and rollback are demonstrated before cutover.

## Explicit constraints

- No paid VPS, paid database, paid domain, paid API plan, or account upgrade without user approval.
- No secrets committed to Git.
- No destructive changes to `main`.
- No claim of 24/7 production availability until the VPS is provisioned, deployed, and externally health-checked.
