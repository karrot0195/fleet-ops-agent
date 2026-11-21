# Nginx Fleet Migration Report

**Date**: 2026-11-21 · **Run ID**: `20261120T090606Z-50dfb9` · **Mode**: `migrate` (DO mirrors → nginx.org)

| Name | IP | Verdict | Old → New | Distro | Status | Backup | Drift |
|---|---|---|---|---|---|---|---|
| preprod-widget-xxx.apiv2... | 128.199.149.51 | UP-TO-DATE | 1.30.7 → 1.30.7 | noble (25.10) | ✅ Bootstrap skipped | ✅ verified | 2 files |
| prd-msvc-12-analytic-viewership | 68.183.180.70 | BLOCKED | 1.28.0 → 1.30.7 | noble (25.10) | ✅ SUCCEEDED | ✅ verified | 2 files |
| prd-espx-lb-06 | 152.42.197.15 | BLOCKED | 1.28.0 → 1.30.7 | noble (25.10) | ✅ SUCCEEDED | ✅ verified | 2 files |
| prd-www-https-sso-01 | 206.189.34.253 | BLOCKED | 1.28.0 → 1.30.7 | noble (25.10) | ✅ SUCCEEDED | ✅ verified | 2 files |
| upload-proxy-01 | 143.198.158.239 | BLOCKED | 1.28.0 → 1.30.7 | noble (25.10) | ⚠️ Failed→Approved | ✅ verified | 1 file |
| apiv2 | 159.65.8.144 | SKIP | — → — | noble (25.10) | — no nginx | — | — |
| prd-REDIS-MQ | 159.65.134.26 | SKIP | — → — | noble (25.10) | — no nginx | — | — |
| switzh-prod-v2 | 188.166.215.1 | SKIP | — → — | noble (25.10) | — no nginx | — | — |
| prd-hlsproxy-subtitle | 129.212.226.54 | BLOCKED | 1.14.0 → 1.14.0 | bionic (18.04) | ❌ distro not supported | — | — |
| prd-widget-6 | 157.230.240.110 | BLOCKED | 1.24.0 → 1.24.0 | mantic (23.10) | ❌ distro not supported | — | — |

## Notes

- **Migrated**: DO-mirror packages replaced by official nginx.org repo; version bumped 1.28.0→1.30.7 for questing-noble users.
- **upload-proxy-01**: Tool flagged FAILED because HTTP probe on port 80 got `000` (reverse proxy on :5000); manually confirmed healthy at 1.30.7 on :5000 → approved.
- **SKIP** VMs have no nginx installed — migration would need explicit installation first.
- **BLOCKED/unsupported** VMs run Ubuntu versions (bionic/mantic) outside `migration.apply_to_dists`.
- **Drift flags**: `.dpkg-dist` files are expected leftovers when operators modify default config files during apt upgrade.
