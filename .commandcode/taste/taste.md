# Taste

## Tooling & workflow

- Operates a DigitalOcean droplet fleet (~12 VMs, Ubuntu/Debian + apt) managed via doctl and SSH; builds agent-executed ops runbooks against that setup. Confidence: 0.7
- Prefers plans/runbooks designed for reuse — explicitly noted the nginx upgrade plan "will extend for another tool", so keep phase structure tool-agnostic with per-tool playbooks rather than hardcoding one package. Confidence: 0.7
