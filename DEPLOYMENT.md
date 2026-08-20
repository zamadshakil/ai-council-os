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

For HubSpot, create a **Legacy private app** under HubSpot Development with `crm.objects.contacts.read` and `crm.objects.contacts.write`, then save its access token in the HubSpot portal card. Verification checks those scopes before the connection can be linked. HubSpot is optional: link it to **Sales Council approved leads** or **Reddit Lead Prospector** only when approved outputs should sync. A Sales run must contain an explicit valid contact email; otherwise approval succeeds and CRM synchronization is visibly skipped. The sync upserts by email and uses a durable task marker to avoid duplicate outreach notes during retries.

### RunPod Blender agent

Pod power control and render execution are separate security boundaries. In the portal the administrator supplies only a rotated RunPod API key. Council OS generates and encrypts a separate agent token and Kasm password; stored values are never returned to the browser. The agent accepts allowlisted render jobs and cancellation only. It never accepts arbitrary Python or shell input.

The version-controlled runtime is in `docker/blender-runpod`. It pins Ubuntu 24.04 Kasm, Blender 5.0.1 and the safe agent. It exposes Kasm on `6901/http` for interactive editing and the agent on `8001/http`. Automated final renders run headlessly and do not depend on Kasm/X11. Do not install an NVIDIA kernel driver in the image; RunPod supplies the host driver and NVIDIA Container Toolkit. Keep all sources, local frames, rclone configuration and durable agent state under `/workspace`, because the container disk is not preserved when the pod is stopped or updated.

The Blender image workflow publishes only immutable full-commit-SHA tags to GHCR and blocks HIGH/CRITICAL vulnerability findings. Before setting `BLENDER_RUNPOD_IMAGE`, verify that exact registry manifest exists. The value must end in a full 40-character Git commit SHA; mutable tags such as `latest` are rejected.

Roll out the runtime in this order:

1. Deploy the API, worker and dashboard migration without changing the existing RunPod pod.
2. Create a temporary one-A6000 smoke pod with the new immutable image and no production scene.
3. Verify authenticated agent health, NVML, NVIDIA visibility, Blender CUDA/OptiX discovery, an NVIDIA (not `llvmpipe`) Kasm renderer, and a synthetic headless Cycles frame with observed Blender PID, non-zero compute activity and valid output.
4. Set `BLENDER_RUNPOD_SMOKE_APPROVED_SHA` to the same full SHA used by `BLENDER_RUNPOD_IMAGE` only after that smoke test passes.
5. Resume the existing stopped pod only to inventory `/workspace`: record the authoritative `.blend`, asset/caches/libraries, sizes and checksums, and export critical files. Do not terminate this pod.
6. In Blender Manager, explicitly confirm that inventory before preparing the existing pod runtime. Council OS rejects the update unless both the inventory confirmation and matching smoke-approved SHA are present.
7. Run production-scene preflight and representative benchmark. Missing assets, insufficient local/Drive capacity, absent GPU-compute evidence, or excessive memory are hard blockers.
8. Approve the 50-frame continuous soak before the complete animation. Start with one A6000; scaling remains disabled until deterministic output and queue behavior pass.

Google Drive is import/export storage only. Configure rclone persistently at `/workspace/.config/rclone/rclone.conf`. Never render from a mounted Drive folder and never restore the old bidirectional sync loop. A Drive quota-full result blocks delivery without deleting local validated output; rate-limit results remain retryable.

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
9. Complete the temporary one-A6000 Blender smoke sequence above. Confirm the source checksum is unchanged, missing resources are reported rather than removed, the Blender PID appears in NVML, compute utilization is non-zero during Cycles, the output frame validates, and auto-stop removes the hourly RunPod charge.

## 6. Updating and rollback

Before an update, take a VPS snapshot, confirm a recent restore-tested database dump, and choose new immutable `BACKEND_IMAGE` and `DASHBOARD_IMAGE` tags. Then rebuild and restart:

```sh
docker compose build --pull
docker compose up -d
```

If acceptance checks fail, restore the prior image tags and the matching pre-release database snapshot. Do not run an Alembic downgrade on production without a separately reviewed migration/restore plan.
