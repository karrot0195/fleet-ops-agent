### PROJECT SUMMARY 

Automation project for auditing and upgrading nginx on a fleet of DigitalOcean VMs. VM IPs are collected via doctl into ip.txt (already populated); each VM is checked for nginx presence, version, and configuration drift, producing a per-VM plan under plan/{ip}.md. Plans are summarized for user confirmation, then executed with local config backups for rollback, processing VMs in parallel behind confirmation gates. Only PLAN.md and ip.txt exist so far; no implementation code yet. The agent-skills submodule provides the agent workflow tooling.


### ARCH DEFINE

Framework: TBD
Language: TBD
Database: TBD
Unit Test Framework: TBD


### RULES


### VERIFICATION SKILLS
load from @.specific/project.yaml   # `skills:` holds runnable verification recipes


### PROJECT FEATURES
load from @.specific/project-features.yaml
