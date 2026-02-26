"""Configuration loading and validation."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def load_config(config_path: str | Path) -> dict:
    """
    Load configuration from a YAML file.

    Handles template nesting (if config has a 'template' key, unwraps it).

    Args:
        config_path: Path to YAML config file

    Returns:
        Configuration dictionary
    """
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    if config is None:
        config = {}

    # Handle template nesting
    if "template" in config:
        config = config["template"]

    return config


def merge_task_config(task_config: dict, template_config: dict) -> dict:
    """
    Merge task-specific config with template defaults.

    Task values override template values. Nested dicts are merged recursively.

    Args:
        task_config: Task-specific configuration
        template_config: Template/default configuration

    Returns:
        Merged configuration dictionary
    """
    import copy

    config = copy.deepcopy(template_config)

    for key, value in task_config.items():
        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value

    return config


def get_provider_config(config: dict) -> tuple[str, dict]:
    """
    Determine provider from config and return (provider_key, agent_config).

    Args:
        config: Full configuration dictionary

    Returns:
        Tuple of (provider_key, agent_config) where provider_key is
        'claude_web' or 'chatgpt_web'
    """
    agent_type = config.get("agent_type", "claude_web")
    if agent_type == "chatgpt_web":
        return "chatgpt_web", config.get("chatgpt_web", {})
    return "claude_web", config.get("claude_web", {})
