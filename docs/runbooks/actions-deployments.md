# Deploy through GitHub Actions

CI checks the application, builds its image, and publishes it to GitHub
Container Registry. Staging deployment and production promotion use
separate workflows that are started manually.

## Before starting

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

Registry image:

```text
ghcr.io/szin7/application-operations-platform@sha256:0e69f74d141520a8aece9600b0ef1ab8b9c07d0ee4d80ac56484a2029d1a5850
```

The production backup was saved in
`backups/20261113T014802Z-JkSafR` before deployment.

These environments run locally on the same laptop.
