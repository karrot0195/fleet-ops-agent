# Contract: Tool Registry

**Version**: 1.0 | **Status**: Draft

## Overview

Tools are registered via `.specific/{tool}.yaml` configuration files. Each tool defines the metadata needed for survey (audit), execute (upgrade), and rollback operations.

## Schema

```yaml
apiVersion: fleet-upgrade-tool/v1
tool:
  name: string              # Required: unique identifier
  package: string           # Required: OS package name
  service: string           # Required: systemd service name
  config_paths: list[str]   # Required: paths to backup/restore
  version_query: string     # Required: command to query version
  precheck: string          # Required: command to verify health
  allowed_origin_patterns: list[str]  # Optional: package origin allowlist
  hold_patterns: list[str]          # Optional: package hold patterns
  drift_patterns: list[str]         # Optional: config drift patterns
  verify:                           # Optional: post-upgrade verification
    http:
      enabled: bool
      url: string
      timeout: int
    https:
      enabled: bool | "auto"
      url: string
      timeout: int
    require_status: list[int]
  upgrade_command: string   # Optional: command template with {package}

migration:                  # Optional: migration mode config
  enabled: bool
  repo_url: string
  repo_dist: string
  apply_to_dists: list[str]
  key_url: string
  key_fingerprint: string
  keyring_path: string
  sources_path: string
  pin_path: string
  pin_priority: int
  prereq_packages: list[str]
  upgrade_command: string
```

## Required Fields

| Field | Validation |
|-------|------------|
| tool.name | Non-empty, unique across all `.specific/*.yaml` |
| tool.package | Non-empty |
| tool.service | Non-empty |
| tool.config_paths | Non-empty list |
| tool.version_query | Non-empty, must return version string on stdout |
| tool.precheck | Non-empty, must exit 0 on success |

## Conditional Fields

When `migration.enabled: true`:
- migration.repo_url, repo_dist, key_url, key_fingerprint, keyring_path, sources_path: required
- migration.apply_to_dists: required, non-empty list
- migration.key_fingerprint: must be exactly 40 hex characters
- migration.pin_priority: integer 1-1000
- migration.upgrade_command: must contain `{package}` placeholder

## Tool Lifecycle

### Registration

1. Operator creates `.specific/{tool}.yaml` with required fields.
2. Skill validates the config at preflight (`doctor` command).
3. Tool appears in `fleet.py survey --list-tools` output.

### Survey (Audit)

For each VM, the skill:
1. Runs `tool.version_query` to get installed version.
2. Checks for available upgrades via package manager.
3. Runs `tool.precheck` to verify current health.
4. Checks package origin against `allowed_origin_patterns`.
5. Checks for holds matching `hold_patterns`.
6. Scans for drift files matching `drift_patterns`.
7. Assigns verdict: SKIP, UP-TO-DATE, UPGRADE, BLOCKED, or UNREACHABLE.

### Execute (Upgrade)

For each approved VM:
1. Backup `tool.config_paths` to local archive.
2. Verify backup checksum.
3. Run `upgrade_command` (or default apt-get upgrade).
4. Run `tool.precheck` to verify post-upgrade health.
5. Run `tool.version_query` to confirm new version.
6. If `tool.verify` is configured, run HTTP/HTTPS checks.

### Rollback

For a failed VM:
1. Restore `tool.config_paths` from backup archive.
2. Reinstall old package version (via `apt-get install {package}={old_version}`).
3. Run `tool.precheck` to verify restored state.
4. Restart `tool.service`.

## Built-in Tools

### nginx

Pre-configured in `.specific/nginx-fleet.yaml` (existing). The new skill reads this config and treats nginx as a registered tool.

### docker

Example registration:
```yaml
apiVersion: fleet-upgrade-tool/v1
tool:
  name: docker
  package: docker-ce
  service: docker
  config_paths:
    - /etc/docker
  version_query: "docker --version | awk '{print $3}'"
  precheck: "docker info > /dev/null 2>&1"
  allowed_origin_patterns:
    - download.docker.com
  hold_patterns:
    - docker-ce
    - docker-ce-cli
  drift_patterns:
    - "*.dpkg-dist"
  verify:
    http:
      enabled: false
```

## Extension Points

New tools can be added by:
1. Creating `.specific/{tool}.yaml` with required fields.
2. Testing `version_query` and `precheck` on a single VM.
3. Running `fleet.py survey --tool {tool} --all` to verify audit works.

No changes to the core skill are required.

## Backward Compatibility

The existing `.specific/nginx-fleet.yaml` is a valid tool config. The new skill:
- Reads the `tool` section as the tool registration.
- Reads the `migration` section as the migration config.
- Ignores the `fleet`, `paths`, `ssh`, `execution`, `logging` sections (handled by global config).

Operators can continue using the existing config without modification.
