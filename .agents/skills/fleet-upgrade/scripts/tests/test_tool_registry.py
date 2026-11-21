"""Unit tests for tool config loading and validation."""

from __future__ import annotations

import os
import tempfile
import unittest

from fleetkit.tools.registry import load_tool_config, list_tools, ToolConfigError, validate_tool_config


class TestToolValidation(unittest.TestCase):
    """Validate tool config schema enforcement."""

    def _valid_config(self):
        return {
            "apiVersion": "fleet-upgrade-tool/v1",
            "tool": {
                "name": "nginx",
                "package": "nginx",
                "service": "nginx",
                "config_paths": ["/etc/nginx"],
                "version_query": "dpkg-query -W -f='${Version}' nginx",
                "precheck": "nginx -t",
                "allowed_origin_patterns": ["archive.ubuntu.com"],
                "hold_patterns": ["nginx"],
                "drift_patterns": ["*.dpkg-dist"],
                "verify": {
                    "http": {"enabled": False, "url": "", "timeout": 10},
                    "https": {"enabled": "auto", "url": "", "timeout": 10},
                    "require_status": [],
                },
            },
            "migration": {"enabled": False},
        }

    def test_valid_config_passes(self):
        validate_tool_config(self._valid_config())

    def test_missing_api_version_fails(self):
        cfg = self._valid_config()
        cfg["apiVersion"] = "wrong/v1"
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_missing_tool_name_fails(self):
        cfg = self._valid_config()
        del cfg["tool"]["name"]
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_empty_tool_package_fails(self):
        cfg = self._valid_config()
        cfg["tool"]["package"] = ""
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_empty_config_paths_fails(self):
        cfg = self._valid_config()
        cfg["tool"]["config_paths"] = []
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_migration_required_fields(self):
        cfg = self._valid_config()
        cfg["migration"]["enabled"] = True
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_migration_full_config_passes(self):
        cfg = self._valid_config()
        m = cfg["migration"]
        m["enabled"] = True
        m.update({
            "repo_url": "https://example.com/repo",
            "repo_dist": "noble",
            "key_url": "https://example.com/key.asc",
            "key_fingerprint": "0" * 40,
            "keyring_path": "/usr/share/keyrings/example.gpg",
            "sources_path": "/etc/apt/sources.list.d/example.list",
            "apply_to_dists": ["noble"],
            "pin_priority": 900,
            "prereq_packages": ["curl", "gnupg"],
            "upgrade_command": "apt-get install {package}",
        })
        validate_tool_config(cfg)

    def test_invalid_key_fingerprint_length(self):
        cfg = self._valid_config()
        m = cfg["migration"]
        m["enabled"] = True
        m["key_fingerprint"] = "SHORT"
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)

    def test_pin_priority_out_of_range_low(self):
        cfg = self._valid_config()
        m = cfg["migration"]
        m["enabled"] = True
        m.update({k: k if isinstance(k, str) else "val" for k in [
            "repo_url", "repo_dist", "key_url", "key_fingerprint", "keyring_path", "sources_path"
        ]})
        m["key_fingerprint"] = "0" * 40
        m["apply_to_dists"] = ["noble"]
        m["prereq_packages"] = []
        m["upgrade_command"] = "apt-get install {package}"
        m["pin_priority"] = 0
        with self.assertRaises(ToolConfigError):
            validate_tool_config(cfg)


class TestListTools(unittest.TestCase):
    """Test scanning .specific/*.yaml for registered tools."""

    def test_list_tools_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            specific_dir = os.path.join(tmp, ".specific")
            os.makedirs(specific_dir)

            tool1 = os.path.join(specific_dir, "nginx.yaml")
            with open(tool1, "w") as f:
                f.write("apiVersion: fleet-upgrade-tool/v1\ntool:\n  name: nginx\n  package: nginx\n  service: nginx\n  config_paths: [/etc/nginx]\n  version_query: nginx -v\n  precheck: nginx -t\n")

            tool2 = os.path.join(specific_dir, "docker.yaml")
            with open(tool2, "w") as f:
                f.write("apiVersion: fleet-upgrade-tool/v1\ntool:\n  name: docker\n  package: docker-ce\n  service: docker\n  config_paths: [/etc/docker]\n  version_query: docker --version\n  precheck: docker info\n")

            non_tool = os.path.join(specific_dir, "provider.yaml")
            with open(non_tool, "w") as f:
                f.write("apiVersion: fleet-upgrade-provider/v1\nprovider:\n  name: doctl\n")

            tools = list_tools(tmp)
            self.assertIn("nginx", tools)
            self.assertIn("docker", tools)
            self.assertNotIn("doctl", tools)


class TestLoadToolConfig(unittest.TestCase):
    """Test loading a tool config from file."""

    def test_load_valid_tool_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            specific_dir = os.path.join(tmp, ".specific")
            os.makedirs(specific_dir)
            path = os.path.join(specific_dir, "test-tool.yaml")
            with open(path, "w") as f:
                f.write("apiVersion: fleet-upgrade-tool/v1\n")
                f.write("tool:\n  name: test-tool\n  package: test-pkg\n  service: test-svc\n")
                f.write("  config_paths: [/etc/test]\n  version_query: test --version\n")
                f.write("  precheck: test -t\n")
            cfg = load_tool_config(tmp, "test-tool")
            self.assertEqual(cfg["tool"]["name"], "test-tool")

    def test_load_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ToolConfigError):
                load_tool_config(tmp, "nonexistent")


if __name__ == "__main__":
    unittest.main()
