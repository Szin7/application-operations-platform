# Deploy with Ansible

Ansible coordinates the existing local deployment procedure. It validates
the release, checks the running lab, calls the backup and deployment scripts,
then verifies readiness and data preservation. Bootstrap and migrations stay
in `scripts/deploy.sh`, so there is one implementation of those operations.

The inventory has one local host, `lab`. Staging and production are separate
Compose projects on that host, not separate machines. No SSH connection,
privilege escalation, or additional Ansible collection is required.

This workflow was added after Nginx. The earlier private-repository Actions
deployments remain historical evidence. These playbooks run manually in WSL
and do not enable the publicly gated Actions deployment jobs.

## Prerequisites

Run from the repository root with:

- Ansible Core 2.20.1, Python 3.14, Docker Compose, and uv available.
- Both application/database pairs and both Nginx proxies running healthy.
- `.env.staging` and `.env.production` as regular files with mode `0600`.
- The original production ticket record in `backups/rollback-check.json`.
- The selected release image already present locally with its source label
  matching the 12-character commit tag.

Use the [registry release procedure](registry-releases.md) to prepare a tested
image. The playbook does not build, pull, or retag images. This is a deployment
workflow for the prepared lab, not a fresh-host provisioning playbook.
Keep the checkout and image tags unchanged during execution. Run one local
deployment at a time; the playbook does not lock out other deployment commands.

## Validate the playbooks and current lab

```bash
./scripts/check_ansible.sh
ansible-playbook -i ansible/inventory.yml ansible/preflight.yml
```

The script checks syntax only. CI runs it with Ansible Core pinned to 2.20.1
in an isolated uv environment; it does not connect to this lab or execute
deployment tasks. Ansible is not added to the application's dependencies.

The preflight checks local execution, Docker/Compose/uv access, environment
file permissions, six container health states, and four readiness endpoints.
It does not read credentials or request deployment changes.

## Check and deploy staging

Enter the full local release tag, such as the recorded release
`application-operations-platform:a56088c1b7bb`:

```bash
read -r -p "Local release image: " release_image

ansible-playbook -i ansible/inventory.yml ansible/deploy.yml \
  -e target_environment=staging \
  -e "release_image=$release_image" \
  --check
```

Check mode validates the lab, release identity, and original production
ticket. A temporary container reads the selected image's application version
with no network access, a read-only filesystem, and resource restrictions.
Backup, deployment, and evidence-writing tasks are skipped. Passing check
mode does not predict migration success or prove a completed deployment.

After those checks pass, use the same terminal and selected release:

```bash
ansible-playbook -i ansible/inventory.yml ansible/deploy.yml \
  -e target_environment=staging \
  -e "release_image=$release_image"
```

The live run calls `scripts/deploy.sh`, which repeats bootstrap, applies
pending migrations, starts the API, and saves the selected release. Ansible
checks the target image and version, readiness through direct and proxy
ports, and the saved `APP_IMAGE` setting. It also checks the original
production ticket and verifies that the production API, both databases,
and both proxies kept their IDs, images, start times, and healthy states.

## Deploy production

Keep the same selected image after staging succeeds:

```bash
ansible-playbook -i ansible/inventory.yml ansible/deploy.yml \
  -e target_environment=production \
  -e "release_image=$release_image" \
  --check
```

Production requires that exact image running healthy in staging, with its
version matching through both the direct API and the proxy. The original
production ticket must match before the live run creates a backup.

After check mode passes:

```bash
ansible-playbook -i ansible/inventory.yml ansible/deploy.yml \
  -e target_environment=production \
  -e "release_image=$release_image"
```

The backup script must succeed before deployment starts. The post-deployment
checks mirror staging's checks, with the staging API protected from changes.
Both database containers and both proxies must also remain unchanged.

## Read the result

A successful live run prints its verified release and writes a new record
under `backups/ansible-deploy-<environment>-<UTC timestamp>.json` with mode
`0600`. It includes the image ID, source commit, version, configuration
hashes, verification results, and production backup path when applicable.
Ticket contents and credentials are not included. These local records and
database backups are excluded from Git.

Repeated live runs execute the deployment procedure and create fresh evidence.
Production also creates a fresh backup. The playbook reports those actions
as changes even when the same application release remains running; it does
not claim a zero-change repeat run. Bootstrap and migrations retain the
existing scripts' repeatable behavior.

## If a run fails

Read the failing task before rerunning. A release or ticket mismatch stops
the workflow before backup and deployment. A backup failure stops it before
deployment. A failure during deployment or subsequent verification may leave
the requested release partially or fully applied; absence of a success record
does not mean nothing changed.

There is no automatic rollback. Inspect readiness and container logs, then
follow [application rollback](deployment-rollback.md) if needed. The normal
preflight requires a healthy lab, so this playbook is not the outage-recovery
entry point. Rollback still requires the image's migration revision to match
the database; it does not undo database migrations.

## Verified rehearsals — 13 November 2026

Both rehearsals used the already-running release `a56088c1b7bb`, application
version `0.1.2`, with Ansible Core 2.20.1 and Python 3.14.4. The order was
preflight, staging check mode, staging live run, production check mode,
then production live run.

| Run | OK | Changed | Failed | Unreachable |
| --- | --- | --- | --- | --- |
| Initial preflight | 9 | 0 | 0 | 0 |
| Staging check mode | 23 | 0 | 0 | 0 |
| Staging live run | 35 | 2 | 0 | 0 |
| Production check mode | 26 | 0 | 0 | 0 |
| Production live run | 39 | 3 | 0 | 0 |

Staging evidence:
`backups/ansible-deploy-staging-20261113T050021364380Z.json`.

Production backup, created before deployment:
`backups/20261113T050247Z-OWcabu`.

Production evidence:
`backups/ansible-deploy-production-20261113T050313711191Z.json`.

Both runs passed all four readiness checks, selected-release and version
checks, saved-release verification, original production ticket comparison,
and protected-container comparison. Staging reported changes for executing
deployment and saving evidence. Production additionally reported the backup.

These were same-release rehearsals. They did not demonstrate an application
upgrade, a new schema migration, API container replacement, or recovery from
a deliberately failed deployment. The new production backup was created
and checked by the backup script, but was not independently restored in this
exercise. The earlier backup recovery remains a separate verified result.
