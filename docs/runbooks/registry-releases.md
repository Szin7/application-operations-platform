# Registry releases

GitHub Actions checks the code, runs the database tests, builds the image,
and checks its contents and runtime user.

After successful checks on main, a separate job publishes that same image
to GitHub Container Registry. Pull requests run checks without publishing.
Deployments to staging and production are started manually.

## Verified release

Verified on 12 November 2026, UTC.

| Item | Recorded value |
| --- | --- |
| Source commit | `4f28d94d3c707699a525fef3153b6cd85166fe05` |
| Application version | `0.1.1` |
| Registry tag | `ghcr.io/szin7/application-operations-platform:4f28d94d3c70` |
| Local deployment tag | `application-operations-platform:4f28d94d3c70` |
| Staging API | `http://127.0.0.1:8002` |
| Production API | `http://127.0.0.1:8003` |

[Successful CI and publishing run](https://github.com/Szin7/application-operations-platform/actions/runs/43279612863)

Registry digest reference:

```text
ghcr.io/szin7/application-operations-platform@sha256:8551ce22d4109610ac45cecf14efd90dd9d526bab655df09700fdac24078bc82
```

## Pull a release

For a private image, sign Docker into GHCR using a classic personal access
token with read:packages permission. Enter the token at the password prompt.

```bash
docker login ghcr.io --username Szin7
```

For the verified release:

```bash
registry_image="ghcr.io/szin7/application-operations-platform@sha256:8551ce22d4109610ac45cecf14efd90dd9d526bab655df09700fdac24078bc82"
release_commit="4f28d94d3c707699a525fef3153b6cd85166fe05"
local_image="application-operations-platform:${release_commit:0:12}"

docker pull "$registry_image"
```

Check that the image's source label matches the release commit:

```bash
docker image inspect "$registry_image" \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The deployment scripts expect a local commit tag. Add that name to the
downloaded image:

```bash
docker image tag "$registry_image" "$local_image"
```

If that local tag already exists, compare its image ID with the downloaded
image before tagging. Stop if they differ.

For another release, take its commit and digest from its successful CI run.
A commit tag can be reassigned; use the digest when selecting the image.

## Deploy through staging

Keep the release variables in the same terminal.

```bash
./scripts/deploy.sh staging "$local_image"
```

Check readiness, version, and the running image ID before continuing.
The running image ID must match the downloaded image's local ID.

Back up production, then deploy:

```bash
./scripts/backup_db.sh .env.production application-operations-production &&
./scripts/deploy.sh production "$local_image"
```

The deployment script requires the requested image to be running healthy
in staging before it changes production.

After deployment, check production readiness, version, running image ID,
saved APP_IMAGE setting, and an existing ticket.

## Recorded results

- CI checks and image publishing both passed.
- The image was pulled by its registry digest.
- Its source label matched the recorded commit.
- Runtime checks confirmed version 0.1.1 and UID 10001.
- Local environment files, pytest, and Ruff were absent from the image.
- Staging and production ran the downloaded image.
- Both readiness and version checks passed.
- Both environment files saved the expected deployment tag.
- Every field of production ticket 1 matched the saved rollback record.

The pre-deployment backup was saved to:

```text
backups/20261112T183849Z-JG0oOg/
```

Its archive listing and checksum checks passed. This particular backup was
not restored during the deployment.

## Scope

Staging and production are separate local Docker Compose environments on
the same laptop. CI publishes images; it does not deploy to the laptop.

See [Deployment and application rollback](deployment-rollback.md) for
rollback commands and [Database backup and restore](backup-restore.md)
for the separately verified restore procedure.
