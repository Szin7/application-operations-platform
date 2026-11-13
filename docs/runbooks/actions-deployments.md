# Deploy through GitHub Actions

CI checks the application, builds its image, and publishes it to GitHub
Container Registry. Separate, manually triggered workflows were used for
the staging and production deployments recorded below.

## Public repository status

This repository is public. CI runs on GitHub-hosted runners and continues
to check and publish images. The following jobs use the local self-hosted
runner and retain the condition `github.event.repository.private == true`:

- `deploy-staging.yml`
- `deploy-production.yml`
- `runner-check.yml`

Their jobs skip while the repository is public. This is intentional for the
public portfolio; the successful deployment records below come from the
private lab. The workflow definitions are retained for review.

The commands below document that private-lab procedure. They will not
deploy from this public repository. Keep the private-repository guard in
place. Any future Actions deployment setup needs a separate review of
runner access and execution boundaries.

For local deployment and rollback, use the
[deployment runbook](deployment-rollback.md). Those scripts do not depend
on the repository being private. They still require the local environment,
credentials, images, and database setup documented there.

[Deploy with Ansible](ansible-deployments.md) provides the later local
orchestration of those scripts, including preflight, production backup,
and post-deployment verification. It does not change the Actions guards.

The [evidence walkthrough](../evidence.md) can be reviewed without running
the deployment workflows.

## Private-lab prerequisites

Keep WSL, Docker Desktop, and the `appops-wsl` runner service running.

`APP_DEPLOY_ROOT` points to the local deployment checkout. That checkout
must be clean, on `main`, and at the commit used to start the workflow.
Keep it unchanged until the deployment finishes.

The local environment files must already exist. Production verification
also uses the original ticket recorded in `backups/rollback-check.json`.

## Deploy staging

Find a successful CI run:

```bash
gh run list --repo Szin7/application-operations-platform \
  --workflow ci.yml --branch main --limit 5
```

Start staging deployment using that CI run:

```bash
read -r -p "Successful CI run ID: " ci_run_id

gh workflow run deploy-staging.yml \
  --repo Szin7/application-operations-platform \
  --ref main \
  -f "ci_run_id=$ci_run_id"
```

Enter the deployment run ID returned by GitHub and wait for its result:

```bash
read -r -p "Staging deployment run ID: " staging_run_id

gh run watch "$staging_run_id" \
  --repo Szin7/application-operations-platform \
  --exit-status
```

The workflow reads the published digest from the successful CI run,
downloads the image, and checks its source commit. It then deploys
staging and verifies the running image, application version, and readiness.

## Promote production

After the staging deployment succeeds, use its run ID. Keep using the
same terminal so the `staging_run_id` variable remains available.

```bash
gh workflow run deploy-production.yml \
  --repo Szin7/application-operations-platform \
  --ref main \
  -f "staging_run_id=$staging_run_id"
```

Watch the production run:

```bash
read -r -p "Production promotion run ID: " production_run_id

gh run watch "$production_run_id" \
  --repo Szin7/application-operations-platform \
  --exit-status
```

Production promotion checks that the selected staging run succeeded and
that its exact image is still running healthy in staging.

It checks the original production ticket and creates a database backup
before calling the deployment script. After deployment, it checks:

- The production image and application version.
- Readiness in both environments.
- Every field of the original production ticket.
- The release saved in `.env.production`.
- That the staging container was not restarted.

The image is already available on the shared Docker host from staging
deployment. Production promotion reuses that image.

## If a deployment fails

Read the failed step before rerunning the workflow:

```bash
gh run view "$production_run_id" \
  --repo Szin7/application-operations-platform \
  --log-failed
```

For a failed staging deployment, use its run ID instead.

The workflows do not roll back automatically. See
[Deployment and application rollback](deployment-rollback.md) for the
rollback procedure and migration revision check.

Release lookup depends on the CI and staging run logs remaining available.

## Verified promotion

On 13 November 2026:

| Check | Run | Result |
| --- | --- | --- |
| CI and image publishing | [43302633612](https://github.com/Szin7/application-operations-platform/actions/runs/43302633612) | Passed |
| Staging deployment | [43344606433](https://github.com/Szin7/application-operations-platform/actions/runs/43344606433) | Passed; production was not restarted |
| Production promotion | [43347528825](https://github.com/Szin7/application-operations-platform/actions/runs/43347528825) | Passed; original ticket preserved and staging was not restarted |

Application version: `0.1.2`.

Image source commit: `a56088c1b7bbeb049c288095bdd3a25ffdf4715d`.

Running Docker image ID verified during promotion:

```text
sha256:0e69f74d141520a8aece9600b0ef1ab8b9c07d0ee4d80ac56484a2029d1a5850
```

This is the local Docker image ID. The registry reference used for
deployment is recorded separately in the workflow logs.

The production backup was saved in
`backups/20261113T014802Z-JkSafR` before deployment.

These environments run locally on the same laptop.

## Verified rejection check

On 13 November 2026, CI run `43349214382` was deliberately supplied
where the workflow expected a successful staging deployment.

[Run 43351535975](https://github.com/Szin7/application-operations-platform/actions/runs/43351535975)
failed at **Read the successful staging deployment**, with:

> Choose a successful staging deployment from main.

The failure was expected. Verification confirmed:

- The checkout check passed; backup and deployment steps were skipped.
- Staging and production API and database containers retained their IDs,
  images, and start times, and remained healthy.
- Readiness, versions, the original production ticket, and the saved
  production release were unchanged.
- No new backup directories were created.

Local evidence:
`backups/production-guard-20261113T022057Z-cbf9a69e-result.json`.

This check covers rejection of the wrong workflow type, not every
possible invalid promotion input.
