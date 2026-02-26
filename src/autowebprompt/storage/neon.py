"""
Neon REST API client for autowebprompt.

Provisions free-tier PostgreSQL databases via the Neon console API.
Requires ``httpx`` — install with: pip install autowebprompt[storage]
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

NEON_API_BASE = "https://console.neon.tech/api/v2"


@dataclass
class NeonProject:
    """Result of creating a Neon project."""

    project_id: str
    project_name: str
    connection_uri: str
    database_name: str
    role_name: str
    region_id: str


class NeonAPIError(Exception):
    """Raised when the Neon API returns an error."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Neon API error {status_code}: {message}")


class NeonClient:
    """Thin wrapper around the Neon console REST API v2."""

    def __init__(self, api_key: str):
        try:
            import httpx
        except ImportError:
            raise RuntimeError(
                "httpx is required for Neon integration. "
                "Install with: pip install autowebprompt[storage]"
            )

        self._api_key = api_key
        self._client = httpx.Client(
            base_url=NEON_API_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def validate_api_key(self) -> bool:
        """Return ``True`` if the API key is valid (can list projects)."""
        try:
            resp = self._client.get("/projects")
            return resp.status_code == 200
        except Exception as exc:
            logger.debug("API key validation failed: %s", exc)
            return False

    def create_project(
        self,
        name: str = "autowebprompt",
        region_id: str = "aws-us-east-2",
    ) -> NeonProject:
        """Create a new Neon project and return connection details."""
        body = {
            "project": {
                "name": name,
                "region_id": region_id,
            }
        }

        resp = self._client.post("/projects", json=body)

        if resp.status_code not in (200, 201):
            error_msg = resp.text
            try:
                error_msg = resp.json().get("message", resp.text)
            except Exception:
                pass
            raise NeonAPIError(resp.status_code, error_msg)

        data = resp.json()
        project = data["project"]
        connection_uris = data.get("connection_uris", [])

        # The first connection_uri is the default database.
        if connection_uris:
            uri_info = connection_uris[0]
            connection_uri = uri_info["connection_uri"]
            database_name = uri_info.get("database_name", "neondb")
            role_name = uri_info.get("role_name", "")
        else:
            # Fallback: build from databases / roles.
            databases = data.get("databases", [])
            roles = data.get("roles", [])
            database_name = databases[0]["name"] if databases else "neondb"
            role_name = roles[0]["name"] if roles else ""
            connection_uri = ""
            logger.warning(
                "No connection_uri in Neon response — you may need to "
                "retrieve it from the Neon dashboard."
            )

        return NeonProject(
            project_id=project["id"],
            project_name=project["name"],
            connection_uri=connection_uri,
            database_name=database_name,
            role_name=role_name,
            region_id=project.get("region_id", region_id),
        )

    def close(self):
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
