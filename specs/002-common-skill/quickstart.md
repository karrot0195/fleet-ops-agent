# Quickstart: Common Fleet Upgrade Skill

**Feature**: 002-common-skill | **Date**: 2026-11-21

## Prerequisites

- Python 3.11+
- SSH access to fleet VMs
- Provider CLI installed (e.g., `doctl`, `vultr-cli`) or manual inventory file
- PyYAML (`pip install pyyaml`)

## Validation Scenario 1: Register a New Tool

**Goal**: Register Docker as an upgradeable tool and verify the audit works.

### Steps

1. **Initialize tool config**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . config --init --type tool --name docker
   ```
   Expected: `.specific/docker.yaml` created with template values.

2. **Edit the config** to match your environment:
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
   ```

3. **Run preflight**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . doctor
   ```
   Expected: Config validated, SSH credentials checked, provider CLI verified.

4. **Discover fleet** (if not already done):
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . discover
   ```
   Expected: Inventory captured, `ip.txt` updated.

5. **Audit for Docker**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . survey --tool docker --all
   ```
   Expected: Each VM gets a verdict (UPGRADE, UP-TO-DATE, SKIP, BLOCKED, or UNREACHABLE).

6. **View summary**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . summary --tool docker
   ```
   Expected: Grouped verdicts, list of eligible VMs.

### Success Criteria

- `.specific/docker.yaml` exists and is valid.
- `doctor` exits 0.
- `survey` produces a verdict for every VM.
- `summary` shows at least one UPGRADE or UP-TO-DATE VM.

---

## Validation Scenario 2: Register a New Provider

**Goal**: Register Vultr as a discovery provider and verify inventory capture.

### Steps

1. **Initialize provider config**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . config --init --type provider --name vultr
   ```
   Expected: `.specific/vultr.yaml` created.

2. **Edit the config**:
   ```yaml
   apiVersion: fleet-upgrade-provider/v1
   provider:
     name: vultr
     cli_binary: vultr-cli
     auth_check: "vultr-cli account"
     discover_command: "vultr-cli instances --json"
     output_format: json
     ip_field: "main_ip"
     name_field: "label"
   ```

3. **Discover with the new provider**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . discover --provider vultr
   ```
   Expected: VMs fetched from Vultr API, inventory updated.

4. **Verify inventory**:
   ```bash
   cat ip.txt
   ```
   Expected: List of VMs from Vultr.

### Success Criteria

- `.specific/vultr.yaml` exists and is valid.
- `discover --provider vultr` exits 0.
- `ip.txt` contains VMs from Vultr.

---

## Validation Scenario 3: Full Upgrade Cycle (Canary + Fleet)

**Goal**: Execute a complete nginx upgrade with canary, gate, and serial fleet rollout.

### Steps

1. **Preflight**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . doctor
   ```

2. **Discover**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . discover
   ```

3. **Audit**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . survey --tool nginx --all
   ```

4. **Summary gate**: Review the output and note eligible VMs.

5. **Canary** (single VM):
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . execute --tool nginx --phase canary --approve 192.0.2.1 --yes
   ```
   Expected: Backup created, upgrade executed, verification passed.

6. **Canary gate**: Review canary result, then record decision:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . gate --decision proceed
   ```

7. **Fleet rollout** (serial, one VM at a time):
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . execute --tool nginx --phase fleet --approve 192.0.2.2,192.0.2.3 --yes
   ```
   Expected: Each VM upgraded sequentially.

8. **Report**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . report --tool nginx --log
   ```
   Expected: Report written to `wiki/fleet-reports/`, summary appended to `LOGS.md`.

### Success Criteria

- Canary VM upgraded successfully.
- Gate decision recorded.
- Fleet VMs upgraded serially.
- Report generated with before/after versions.
- `LOGS.md` updated.

---

## Validation Scenario 4: Rollback After Failure

**Goal**: Verify that a failed VM can be fully rolled back (package + config).

### Steps

1. **Simulate a failure** (e.g., block the upgrade command on a test VM).

2. **Attempt upgrade**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . execute --tool nginx --phase canary --approve 192.0.2.99 --yes
   ```
   Expected: VM marked FAILED.

3. **Rollback**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . rollback --tool nginx --ip 192.0.2.99 --yes
   ```
   Expected: Package version restored, config restored, service restarted.

4. **Verify**:
   ```bash
   ssh root@192.0.2.99 "dpkg-query -W -f='${Version}' nginx && nginx -t"
   ```
   Expected: Old version, config test passes.

### Success Criteria

- Rollback exits 0.
- Package version matches pre-upgrade version.
- Config files restored from backup.
- Service is running.

---

## Validation Scenario 5: Concurrent Tools

**Goal**: Verify that two tools can be upgraded independently without interference.

### Steps

1. **Register both tools**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . config --init --type tool --name nginx
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . config --init --type tool --name docker
   ```

2. **Audit both**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . survey --tool nginx --all
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . survey --tool docker --all
   ```

3. **Upgrade nginx**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . execute --tool nginx --phase canary --approve 192.0.2.1 --yes
   ```

4. **Verify Docker records unchanged**:
   ```bash
   python3 .agents/skills/fleet-upgrade/scripts/fleet.py --root . summary --tool docker
   ```
   Expected: Docker verdicts unchanged (no Docker records show SUCCEEDED from the nginx run).

### Success Criteria

- Nginx upgrade does not affect Docker records.
- Each tool's records are isolated.
- State.json contains separate records per tool.

---

## Running Tests

```bash
# Unit tests
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests -t .agents/skills/fleet-upgrade/scripts -v

# Contract tests (provider interface, tool registry)
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests/contract -t .agents/skills/fleet-upgrade/scripts -v

# Integration tests (e2e flow)
python3 -m unittest discover -s .agents/skills/fleet-upgrade/scripts/tests/integration -t .agents/skills/fleet-upgrade/scripts -v
```

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| `config not found` | Run `config --init --type tool --name {name}` |
| `SSH env missing` | Create `.personal/ssh.env` with `SSH_USER`, `SSH_KEY`, `SSH_PORT` |
| `doctl executable not found` | Install doctl or switch to `manual` provider |
| `no inventory captured` | Run `discover` before `survey` |
| `non-UPGRADE IP approved` | Only VMs with UPGRADE verdict can be approved |
| `canary has not reached terminal state` | Wait for canary to complete before recording gate decision |
| `rollback refused` | Rollback only valid after a FAILED execution |
