"""Tests for autowebprompt.storage.schema."""

from unittest.mock import MagicMock, patch, call

import pytest

from autowebprompt.storage.schema import (
    SCHEMA_VERSION,
    get_migration_sql,
    run_migration,
    check_connection,
    get_table_status,
)


class TestGetMigrationSql:
    def test_returns_list_of_strings(self):
        stmts = get_migration_sql()
        assert isinstance(stmts, list)
        assert len(stmts) > 0
        for stmt in stmts:
            assert isinstance(stmt, str)

    def test_contains_create_table_statements(self):
        sql = "\n".join(get_migration_sql())
        assert "CREATE TABLE IF NOT EXISTS tasks" in sql
        assert "CREATE TABLE IF NOT EXISTS task_attempts" in sql
        assert "CREATE TABLE IF NOT EXISTS _autowebprompt_meta" in sql

    def test_contains_indexes(self):
        sql = "\n".join(get_migration_sql())
        assert "idx_tasks_task_name" in sql
        assert "idx_task_attempts_task_id" in sql

    def test_returns_fresh_copy(self):
        a = get_migration_sql()
        b = get_migration_sql()
        assert a == b
        assert a is not b


class TestRunMigration:
    @patch("autowebprompt.storage.schema.psycopg2", create=True)
    def test_runs_all_statements(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        # Patch the import inside the function.
        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            version = run_migration("postgresql://test")

        assert version == SCHEMA_VERSION
        mock_psycopg2.connect.assert_called_once_with("postgresql://test")
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

        # Should have executed all migration statements + SET_VERSION.
        stmts = get_migration_sql()
        assert mock_cur.execute.call_count == len(stmts) + 1

    @patch("autowebprompt.storage.schema.psycopg2", create=True)
    def test_rollback_on_error(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur
        mock_cur.execute.side_effect = Exception("SQL error")

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            with pytest.raises(Exception, match="SQL error"):
                run_migration("postgresql://test")

        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_raises_without_psycopg2(self):
        with patch.dict("sys.modules", {"psycopg2": None}):
            with pytest.raises(RuntimeError, match="psycopg2"):
                run_migration("postgresql://test")


class TestTestConnection:
    @patch("autowebprompt.storage.schema.psycopg2", create=True)
    def test_returns_true_on_success(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            assert check_connection("postgresql://test") is True

        mock_cur.execute.assert_called_once_with("SELECT 1")

    @patch("autowebprompt.storage.schema.psycopg2", create=True)
    def test_returns_false_on_failure(self, mock_psycopg2):
        mock_psycopg2.connect.side_effect = Exception("Connection refused")

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            assert check_connection("postgresql://test") is False


class TestGetTableStatus:
    @patch("autowebprompt.storage.schema.psycopg2", create=True)
    def test_returns_status_dict(self, mock_psycopg2):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_psycopg2.connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cur

        # Mock: schema version exists, both tables exist with rows.
        mock_cur.fetchone.side_effect = [
            ("1",),       # schema_version
            (True,),      # tasks exists
            (42,),        # tasks count
            (True,),      # task_attempts exists
            (108,),       # task_attempts count
        ]

        with patch.dict("sys.modules", {"psycopg2": mock_psycopg2}):
            status = get_table_status("postgresql://test")

        assert status["schema_version"] == "1"
        assert status["tables"]["tasks"]["exists"] is True
        assert status["tables"]["tasks"]["rows"] == 42
        assert status["tables"]["task_attempts"]["exists"] is True
        assert status["tables"]["task_attempts"]["rows"] == 108

    def test_dry_run_sql_is_valid(self):
        """Verify the SQL strings are syntactically reasonable."""
        stmts = get_migration_sql()
        for stmt in stmts:
            # Each statement should end with a semicolon.
            assert stmt.strip().endswith(";"), f"Missing semicolon: {stmt!r}"
