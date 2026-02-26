"""Tests for autowebprompt.config.loader module."""

import pytest
import yaml

from autowebprompt.config.loader import load_config, merge_task_config, get_provider_config


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_simple_yaml(self, tmp_path):
        """load_config returns the dict from a plain YAML file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({"agent_type": "claude_web", "timeout": 300}))

        result = load_config(config_file)

        assert result == {"agent_type": "claude_web", "timeout": 300}

    def test_load_unwraps_template_key(self, tmp_path):
        """When YAML has a top-level 'template' key, load_config unwraps it."""
        config_file = tmp_path / "template.yaml"
        data = {"template": {"agent_type": "chatgpt_web", "max_sec": 5400}}
        config_file.write_text(yaml.dump(data))

        result = load_config(config_file)

        assert result == {"agent_type": "chatgpt_web", "max_sec": 5400}

    def test_load_preserves_non_template_keys(self, tmp_path):
        """When no 'template' key exists, the whole dict is returned as-is."""
        config_file = tmp_path / "flat.yaml"
        data = {"provider": "claude", "tasks": ["a", "b"]}
        config_file.write_text(yaml.dump(data))

        result = load_config(config_file)

        assert result == data

    def test_load_file_not_found_raises(self, tmp_path):
        """load_config raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.yaml")

    def test_load_accepts_str_path(self, tmp_path):
        """load_config accepts a string path, not just a Path object."""
        config_file = tmp_path / "str_path.yaml"
        config_file.write_text(yaml.dump({"key": "value"}))

        result = load_config(str(config_file))

        assert result == {"key": "value"}

    def test_load_empty_yaml_returns_empty_dict(self, tmp_path):
        """An empty YAML file returns an empty dict."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        result = load_config(config_file)
        assert result == {}

    def test_load_nested_config(self, tmp_path):
        """load_config handles deeply nested YAML structures."""
        data = {
            "template": {
                "agent_type": "claude_web",
                "claude_web": {
                    "project_id": "abc-123",
                    "browser": {"type": "chrome_canary", "headless": False},
                },
            }
        }
        config_file = tmp_path / "nested.yaml"
        config_file.write_text(yaml.dump(data))

        result = load_config(config_file)

        assert result["agent_type"] == "claude_web"
        assert result["claude_web"]["browser"]["type"] == "chrome_canary"


class TestMergeTaskConfig:
    """Tests for merge_task_config()."""

    def test_task_values_override_template(self):
        """Task-specific values override template defaults."""
        template = {"timeout": 100, "headless": True}
        task = {"timeout": 500}

        result = merge_task_config(task, template)

        assert result["timeout"] == 500
        assert result["headless"] is True

    def test_nested_dicts_are_merged(self):
        """Nested dicts are updated (shallow merge), not replaced entirely."""
        template = {"browser": {"type": "chrome", "headless": False}}
        task = {"browser": {"headless": True}}

        result = merge_task_config(task, template)

        assert result["browser"]["type"] == "chrome"
        assert result["browser"]["headless"] is True

    def test_task_adds_new_keys(self):
        """Keys present in task but not in template are added."""
        template = {"a": 1}
        task = {"b": 2}

        result = merge_task_config(task, template)

        assert result == {"a": 1, "b": 2}

    def test_empty_task_returns_template_copy(self):
        """An empty task config returns a copy of the template."""
        template = {"x": 10, "y": 20}
        task = {}

        result = merge_task_config(task, template)

        assert result == template
        # Ensure it is a copy, not the same object
        assert result is not template

    def test_original_template_not_mutated(self):
        """merge_task_config must not mutate the original template dict."""
        template = {"browser": {"type": "chrome"}}
        task = {"browser": {"headless": True}}

        merge_task_config(task, template)

        assert "headless" not in template["browser"]

    def test_non_dict_value_replaces_dict(self):
        """A non-dict task value replaces a dict template value."""
        template = {"browser": {"type": "chrome"}}
        task = {"browser": "disabled"}

        result = merge_task_config(task, template)

        assert result["browser"] == "disabled"


class TestGetProviderConfig:
    """Tests for get_provider_config()."""

    def test_default_is_claude_web(self):
        """With no agent_type key, defaults to claude_web."""
        config = {}

        provider_key, agent_config = get_provider_config(config)

        assert provider_key == "claude_web"
        assert agent_config == {}

    def test_claude_web_explicit(self):
        """Explicit claude_web agent_type returns claude_web config."""
        config = {
            "agent_type": "claude_web",
            "claude_web": {"project_id": "abc"},
        }

        provider_key, agent_config = get_provider_config(config)

        assert provider_key == "claude_web"
        assert agent_config == {"project_id": "abc"}

    def test_chatgpt_web(self):
        """chatgpt_web agent_type returns chatgpt_web config."""
        config = {
            "agent_type": "chatgpt_web",
            "chatgpt_web": {"project_id": "xyz", "agent_mode": True},
        }

        provider_key, agent_config = get_provider_config(config)

        assert provider_key == "chatgpt_web"
        assert agent_config == {"project_id": "xyz", "agent_mode": True}

    def test_chatgpt_web_missing_section(self):
        """chatgpt_web agent_type with no matching section returns empty dict."""
        config = {"agent_type": "chatgpt_web"}

        provider_key, agent_config = get_provider_config(config)

        assert provider_key == "chatgpt_web"
        assert agent_config == {}

    def test_unknown_agent_type_falls_through_to_claude(self):
        """An unrecognized agent_type falls through to claude_web."""
        config = {"agent_type": "some_other_agent"}

        provider_key, _ = get_provider_config(config)

        assert provider_key == "claude_web"
