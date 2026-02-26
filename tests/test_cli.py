"""Tests for autowebprompt.cli.main module."""

import pytest

click = pytest.importorskip("click", reason="click is required for CLI tests")

from unittest.mock import patch, MagicMock

from click.testing import CliRunner

from autowebprompt.cli.main import cli


@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


class TestCliGroup:
    """Tests for the top-level CLI group."""

    def test_cli_help(self, runner):
        """The CLI group prints help text without errors."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "autowebprompt" in result.output

    def test_cli_version(self, runner):
        """--version flag prints the version string."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "0.1.0" in result.output


class TestCheckCommand:
    """Tests for the 'check' command."""

    def test_check_chrome_found_and_cdp_running(self, runner):
        """check succeeds when Chrome is found and CDP is available."""
        with (
            patch(
                "autowebprompt.browser.manager.find_chrome",
                return_value="/usr/bin/chrome",
            ),
            patch("autowebprompt.browser.manager.is_cdp_available", return_value=True),
        ):
            result = runner.invoke(cli, ["check"])

        assert result.exit_code == 0
        assert "Chrome found" in result.output
        assert "Ready for automation" in result.output

    def test_check_chrome_not_found(self, runner):
        """check fails with exit code 1 when Chrome is not installed."""
        with patch(
            "autowebprompt.browser.manager.find_chrome",
            return_value=None,
        ):
            result = runner.invoke(cli, ["check"])

        assert result.exit_code == 1
        assert "Chrome not found" in result.output

    def test_check_cdp_not_running(self, runner):
        """check fails when Chrome is found but CDP is not running."""
        with (
            patch(
                "autowebprompt.browser.manager.find_chrome",
                return_value="/usr/bin/chrome",
            ),
            patch("autowebprompt.browser.manager.is_cdp_available", return_value=False),
        ):
            result = runner.invoke(cli, ["check"])

        assert result.exit_code == 1
        assert "NOT running" in result.output

    def test_check_custom_port(self, runner):
        """check passes --port to is_cdp_available."""
        with (
            patch(
                "autowebprompt.browser.manager.find_chrome",
                return_value="/usr/bin/chrome",
            ),
            patch(
                "autowebprompt.browser.manager.is_cdp_available",
                return_value=True,
            ) as mock_cdp,
        ):
            result = runner.invoke(cli, ["check", "--port", "9333"])

        assert result.exit_code == 0
        mock_cdp.assert_called_once_with(9333)


class TestTemplatesCommand:
    """Tests for the 'templates' command."""

    def test_templates_displays_info(self, runner):
        """templates command outputs setup instructions."""
        result = runner.invoke(cli, ["templates"])

        assert result.exit_code == 0
        assert "template" in result.output.lower()

    def test_templates_mentions_setup(self, runner):
        """templates command tells the user about 'autowebprompt setup'."""
        result = runner.invoke(cli, ["templates"])

        assert "autowebprompt setup" in result.output


class TestSetupCommand:
    """Tests for the 'setup' command."""

    def test_setup_invokes_wizard(self, runner):
        """setup command calls run_wizard()."""
        with patch("autowebprompt.cli.wizard.run_wizard") as mock_wizard:
            result = runner.invoke(cli, ["setup"])

        mock_wizard.assert_called_once()


class TestRunCommand:
    """Tests for the 'run' command."""

    def test_run_requires_provider(self, runner):
        """run command fails if --provider is not given."""
        result = runner.invoke(cli, ["run"])

        assert result.exit_code != 0
        assert "provider" in result.output.lower() or "Missing" in result.output

    def test_run_requires_tasks(self, runner, tmp_path):
        """run command prints error when --tasks is not provided."""
        with patch("autowebprompt.engine.batch.BatchRunner") as MockRunner:
            mock_instance = MagicMock()
            MockRunner.return_value = mock_instance

            result = runner.invoke(cli, ["run", "--provider", "claude"])

        assert result.exit_code == 1

    def test_run_help(self, runner):
        """run --help shows all expected options."""
        result = runner.invoke(cli, ["run", "--help"])

        assert result.exit_code == 0
        assert "--provider" in result.output
        assert "--tasks" in result.output
        assert "--dry-run" in result.output
        assert "--fetch-from-db" in result.output
