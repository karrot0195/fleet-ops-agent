# Taste
- Operates a DigitalOcean droplet fleet (~12 VMs, Ubuntu/Debian + apt) managed via doctl and SSH; builds agent-executed ops runbooks against that setup. Confidence: 0.7
- Prefers plans/runbooks designed for reuse — explicitly noted the nginx upgrade plan "will extend for another tool", so keep phase structure tool-agnostic with per-tool playbooks rather than hardcoding one package. Confidence: 0.7
- Machine-oriented fleet files must stay human-readable: when a list file holds IPs (e.g. ip.txt), include each VM's droplet name alongside the IP for easy reading. Confidence: 0.7
- Process each item sequentially and stop for explicit e2e verification before proceeding to the next. Confidence: 0.9
- Report outputs should be a single consolidated markdown table with one row per item (e.g., one row per VM), rather than grouped sections. Confidence: 0.8
- Defaults report and fleet summary files to the `./wiki/report/` directory. Confidence: 0.8
