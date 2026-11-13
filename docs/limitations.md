# Scope and limitations

Staging, production, monitoring, and backups share one laptop. This lab
does not demonstrate high availability or recovery after losing the laptop.

Authentication is not implemented. The API uses local loopback addresses.
Local deployments and rollback are manual. Actions deployment jobs are gated
off in this public repository. Historical release lookup depends on retained
GitHub Actions logs.

Backups are local and manually triggered; off-machine storage is not
configured. Recovery was checked using one demonstration ticket without
switching production to the recovered database. Notifications remain local.

The staging recovery drill introduces a temporary API startup configuration
fault using the existing release image. It does not exercise a bad image
promotion through GitHub Actions or an incompatible database migration.
Rollback restores the application only when its migration revision matches
the current database.
