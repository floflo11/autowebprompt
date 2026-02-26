"""Tests for autowebprompt.storage.neon — Neon REST API client."""

from unittest.mock import MagicMock, patch

import pytest

from autowebprompt.storage.neon import NeonClient, NeonAPIError, NeonProject


@pytest.fixture
def mock_httpx():
    """Patch httpx so NeonClient can be constructed without installing it."""
    mock_module = MagicMock()
    mock_client_instance = MagicMock()
    mock_module.Client.return_value = mock_client_instance
    with patch.dict("sys.modules", {"httpx": mock_module}):
        yield mock_module, mock_client_instance


class TestValidateApiKey:
    def test_valid_key(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_client.get.return_value = mock_resp

        client = NeonClient("neon_key_abc")
        assert client.validate_api_key() is True
        mock_client.get.assert_called_once_with("/projects")

    def test_invalid_key(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client.get.return_value = mock_resp

        client = NeonClient("bad_key")
        assert client.validate_api_key() is False

    def test_network_error(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_client.get.side_effect = Exception("timeout")

        client = NeonClient("neon_key_abc")
        assert client.validate_api_key() is False


class TestCreateProject:
    def test_success(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "project": {
                "id": "proj-abc123",
                "name": "autowebprompt",
                "region_id": "aws-us-east-2",
            },
            "connection_uris": [
                {
                    "connection_uri": "postgresql://user:pass@ep-abc.us-east-2.aws.neon.tech/neondb",
                    "database_name": "neondb",
                    "role_name": "user",
                }
            ],
            "databases": [{"name": "neondb"}],
            "roles": [{"name": "user"}],
        }
        mock_client.post.return_value = mock_resp

        client = NeonClient("neon_key_abc")
        project = client.create_project(name="autowebprompt", region_id="aws-us-east-2")

        assert isinstance(project, NeonProject)
        assert project.project_id == "proj-abc123"
        assert project.project_name == "autowebprompt"
        assert "neon.tech" in project.connection_uri
        assert project.database_name == "neondb"
        assert project.role_name == "user"

        mock_client.post.assert_called_once_with(
            "/projects",
            json={
                "project": {
                    "name": "autowebprompt",
                    "region_id": "aws-us-east-2",
                }
            },
        )

    def test_api_error(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_resp.text = "Validation failed"
        mock_resp.json.return_value = {"message": "Validation failed"}
        mock_client.post.return_value = mock_resp

        client = NeonClient("neon_key_abc")
        with pytest.raises(NeonAPIError) as exc_info:
            client.create_project()

        assert exc_info.value.status_code == 422
        assert "Validation failed" in str(exc_info.value)

    def test_fallback_without_connection_uris(self, mock_httpx):
        _, mock_client = mock_httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "project": {
                "id": "proj-xyz",
                "name": "test",
                "region_id": "aws-us-east-2",
            },
            "connection_uris": [],
            "databases": [{"name": "mydb"}],
            "roles": [{"name": "admin"}],
        }
        mock_client.post.return_value = mock_resp

        client = NeonClient("neon_key_abc")
        project = client.create_project()

        assert project.project_id == "proj-xyz"
        assert project.connection_uri == ""
        assert project.database_name == "mydb"
        assert project.role_name == "admin"


class TestContextManager:
    def test_close(self, mock_httpx):
        _, mock_client = mock_httpx
        client = NeonClient("key")
        client.close()
        mock_client.close.assert_called_once()

    def test_context_manager(self, mock_httpx):
        _, mock_client = mock_httpx
        with NeonClient("key") as client:
            pass
        mock_client.close.assert_called_once()
