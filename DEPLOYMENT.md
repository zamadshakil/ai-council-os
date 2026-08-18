# AI Council OS production deployment

This deployment exposes only Caddy on ports 80/443. PostgreSQL, FastAPI, the durable worker, and Next.js remain on the private Compose network.

## 1. Security gate

Do not reuse any credential that has appeared in chat, a document, a screenshot, source control, or a previous `.env` file.

Before launch:

1. Revoke and replace the OpenRouter and RunPod keys.
2. Replace the Hostinger root password and the dashboard administrator password.
3. Generate a new internal service token with at least 32 random characters.
4. Generate a new integration-vault encryption key and keep it outside source control and application-code backups.
5. Generate fresh Telegram/webhook secrets and OAuth credentials where applicable.
6. Create a non-root VPS deployment user with an SSH key. Verify the key in a second terminal before disabling root password login.
7. Permit only SSH, HTTP, and HTTPS in the VPS firewall, then take a Hostinger VPS snapshot.

The application intentionally refuses to start in production when the administrator password is weak, the internal service token is too short, or the public origin is not HTTPS.

## 2. Host and environment

Point no DNS record. Choose the sslip.io name derived from the server IPv4 address. For example, IP `203.0.113.10` can use `203-0-113-10.sslip.io`.

```sh
cp .env.example .env
chmod 600 .env
mkdir -p credentials
```

Fill `.env` only with newly rotated values. Set `PUBLIC_HOST` to the sslip.io hostname without `https://`. Place the YouTube OAuth file at `credentials/youtube_token.json`; do not commit it.

Generate the integration-vault key once, copy it into `INTEGRATION_ENCRYPTION_KEY`, and store a recovery copy in the deployment password manager. Losing this key makes the encrypted provider connections unreadable:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

After the first login, use **Settings & Integrations** to add each provider. The browser can write a replacement credential set but can never read stored values back. Verify the provider, then link it to a compatible workflow. Replacing or removing a connection automatically disables linked workflows until their required connections verify again. Environment-based credentials remain only as a first-bootstrap fallback; the portal vault is the normal operating path. Configure RunPod here if Blender Manager is needed. Configure Meta with an Instagram professional account and comment-management permission before enabling Instagram Comment Replies.

### RunPod Blender agent

Pod power control and template execution are separate security boundaries. The RunPod integration stores a rotated RunPod API key plus a different, random `BLENDER_AGENT_TOKEN` of at least 32 characters. Put the same agent token on the pod, expose port `8001/http` in its RunPod template, and keep the `.blend` source on the persistent `/workspace` volume.

The GPU pod image must contain a Blender build with Cycles GPU rendering support, Python, and the packages in `blender-agent-requirements.txt`. Include `src/scripts/blender_listener.py` and `src/scripts/blender_job.py`, then start the allowlisted service with:

```sh
python -m uvicorn src.scripts.blender_listener:app --host 0.0.0.0 --port 8001
```

Do not deploy the old raw-script bridge. Do not use a desktop image merely because it exposes a GUI; verify that its Blender build supports the selected GPU backend. The manager accepts only a workspace `.blend` path and bounded render settings, never Python or shell input. A successful smoke test must report `gpu_engaged: true`, the detected backend/device count, a non-empty output copy, and a benchmark frame before production animation work is allowed.

Use a clean PostgreSQL database for the first production release. The old SQLite/demo task data is not imported because it may contain stale or fabricated development records. Export any historically important text separately before launch.

Keep `ROTATE_ADMIN_PASSWORD_ON_STARTUP=1` for the first successful start. After confirming the new login, change it to `0` so a container restart cannot unexpectedly change the stored password.

## 3. Validate and start

```sh
docker compose config --quiet
docker compose build --pull
docker compose up -d
docker compose ps
```

The API container applies Alembic migrations before FastAPI starts. The worker starts only after the API is healthy. No workflow is enabled by seeding; verify its credentials in the dashboard first.

Verify the installation:

```sh
curl --fail "https://${PUBLIC_HOST}/healthz"
curl --fail "https://${PUBLIC_HOST}/readyz"
docker compose exec api alembic current
docker compose logs --since=10m api worker dashboard caddy
```

`/readyz` verifies both PostgreSQL and the approved OpenRouter model IDs. Do not enable schedules until it reports ready and the controlled smoke tests pass.

## 4. Backup and recovery

The `backup` service writes an atomic, verified custom-format PostgreSQL dump and a verified application-data archive each day. It removes files older than `BACKUP_RETENTION_DAYS` and becomes unhealthy when a successful backup is overdue.

List backups without exposing database credentials:

```sh
docker compose exec backup find /backups -maxdepth 1 -type f -name 'council_os_*.dump' -print
```

Test restore into a separate disposable database before launch and after material schema changes. Never test a restore over the production database. Keep the pre-release Hostinger snapshot and previous container image tags until acceptance testing is complete.

```sh
docker compose --profile ops run --rm backup-restore-test
```

This command validates both archives, restores the latest database dump into a temporary database, checks the migrated schema, and removes the temporary database afterward.

## 5. Controlled smoke test

1. Sign in and confirm a page reload preserves the server-managed session.
2. Confirm anonymous API requests and invalid CSRF requests are rejected.
3. Run one low-cost Council task for Grant, Sales, and Content.
4. Approve one item twice and confirm only one decision/publication is recorded.
5. Activate the kill switch, queue a workflow, and confirm the worker does not execute it.
6. Verify Telegram with the single allowed administrator chat.
7. Test YouTube and Reddit with controlled non-production content. Reddit must end in manual-ready state and must never auto-post.
8. Verify Grant DOCX and PDF output visually before manual portal use.
9. Run one low-resolution Blender template job, confirm the original hash is unchanged, confirm GPU proof and the output copy, then confirm auto-stop removes the hourly RunPod charge.

## 6. Updating and rollback

Before an update, take a VPS snapshot, confirm a recent restore-tested database dump, and choose new immutable `BACKEND_IMAGE` and `DASHBOARD_IMAGE` tags. Then rebuild and restart:

```sh
docker compose build --pull
docker compose up -d
```

If acceptance checks fail, restore the prior image tags and the matching pre-release database snapshot. Do not run an Alembic downgrade on production without a separately reviewed migration/restore plan.
