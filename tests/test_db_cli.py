"""Tests for autowebprompt.cli.db — database CLI commands."""

from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest
from click.testing import CliRunner

from autowebprompt.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestDbGroup:
    def test_help(self, runner):
        result = runner.invoke(cli, ["db", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "migrate" in result.output
        assert "status" in result.output

    def test_no_subcommand_shows_usage(self, runner):
        result = runner.invoke(cli, ["db"])
        # Click groups return exit code 2 when invoked without a subcommand.
        assert "Usage" in result.output


class TestDbMigrate:
    def test_dry_run(self, runner):
        result = runner.invoke(cli, ["db", "migrate", "--dry-run"])
        assert result.exit_code == 0
        assert "CREATE TABLE IF NOT EXISTS tasks" in result.output
        assert "CREATE TABLE IF NOT EXISTS task_attempts" in result.output
        assert "_autowebprompt_meta" in result.output

    def test_no_database_url(self, runner):
        """Should fail gracefully when no DATABASE_URL is available."""
        result = runner.invoke(cli, ["db", "migrate"], env={"DATABASE_URL": ""})
        assert result.exit_code != 0
        assert "DATABASE_URL" in result.output

    @patch("autowebprompt.storage.schema.run_migration")
    @patch("autowebprompt.cli.db._load_database_url")
    def test_runs_migration(self, mock_load, mock_migrate, runner):
        mock_load.return_value = "postgresql://test"
        mock_migrate.return_value = "1"

        result = runner.invoke(cli, ["db", "migrate"])
        assert result.exit_code == 0
        assert "schema version 1" in result.output
        mock_migrate.assert_called_once_with("postgresql://test")


class TestDbStatus:
    def test_no_database_url(self, runner):
        result = runner.invoke(cli, ["db", "status"], env={"DATABASE_URL": ""})
        assert result.exit_code != 0
        assert "DATABASE_URL" in result.output

    @patch("autowebprompt.storage.schema.get_table_status")
    @patch("autowebprompt.storage.schema.check_connection")
    @patch("autowebprompt.cli.db._load_database_url")
    def test_shows_status(self, mock_load, mock_check, mock_status, runner):
        mock_load.return_value = "postgresql://test"
        mock_check.return_value = True
        mock_status.return_value = {
            "schema_version": "1",
            "tables": {
                "tasks": {"exists": True, "rows": 10},
                "task_attempts": {"exists": True, "rows": 25},
            },
        }

        result = runner.invoke(cli, ["db", "status"])
        assert result.exit_code == 0
        assert "Connected" in result.output

    @patch("autowebprompt.storage.schema.check_connection")
    @patch("autowebprompt.cli.db._load_database_url")
    def test_connection_failure(self, mock_load, mock_check, runner):
        mock_load.return_value = "postgresql://test"
        mock_check.return_value = False

        result = runner.invoke(cli, ["db", "status"])
        assert result.exit_code != 0
        assert "failed" in result.output.lower()


class TestDbInit:
    @patch("autowebprompt.storage.schema.run_migration")
    @patch("autowebprompt.cli.db._load_database_url")
    def test_uses_existing_url(self, mock_load, mock_migrate, runner):
        """When DATABASE_URL exists and user declines new DB, use existing."""
        mock_load.return_value = "postgresql://existing"
        mock_migrate.return_value = "1"

        result = runner.invoke(cli, ["db", "init", "--api-key", "test"], input="n\n")
        assert result.exit_code == 0
        mock_migrate.assert_called_once_with("postgresql://existing")

    @patch("autowebprompt.cli.db._save_database_url")
    @patch("autowebprompt.storage.schema.check_connection")
    @patch("autowebprompt.storage.schema.run_migration")
    @patch("autowebprompt.storage.neon.NeonClient")
    @patch("autowebprompt.cli.db._load_database_url")
    def test_creates_new_project(
        self, mock_load, mock_neon_cls, mock_migrate, mock_check, mock_save, runner
    ):
        mock_load.return_value = None
        mock_check.return_value = True
        mock_migrate.return_value = "1"
        mock_save.return_value = Path(".env.local")

        from autowebprompt.storage.neon import NeonProject

        mock_client = MagicMock()
        mock_client.validate_api_key.return_value = True
        mock_client.create_project.return_value = NeonProject(
            project_id="proj-123",
            project_name="autowebprompt",
            connection_uri="postgresql://user:pass@host/db",
            database_name="neondb",
            role_name="user",
            region_id="aws-us-east-2",
        )
        mock_neon_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_neon_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = runner.invoke(cli, ["db", "init", "--api-key", "neon_key_test"])
        assert result.exit_code == 0
        assert "Database ready" in result.output
