"""CLI commands for database provisioning and management."""

import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _load_database_url(database_url: str | None, env_file: str | None = None) -> str | None:
    """Resolve DATABASE_URL from flag → env file → environment."""
    if database_url:
        return database_url

    # Try loading from env file.
    if env_file:
        from dotenv import dotenv_values
        values = dotenv_values(env_file)
        url = values.get("DATABASE_URL")
        if url:
            return url

    # Try .env.local in cwd.
    local_env = Path.cwd() / ".env.local"
    if local_env.exists():
        from dotenv import dotenv_values
        values = dotenv_values(local_env)
        url = values.get("DATABASE_URL")
        if url:
            return url

    return os.environ.get("DATABASE_URL")


def _save_database_url(connection_uri: str, env_file: str | None = None) -> Path:
    """Append DATABASE_URL to the target env file (default: .env.local)."""
    target = Path(env_file) if env_file else Path.cwd() / ".env.local"

    # Read existing content (if any) to avoid duplicate keys.
    existing = ""
    if target.exists():
        existing = target.read_text()

    lines = existing.splitlines()
    # Remove any existing DATABASE_URL line.
    lines = [l for l in lines if not l.startswith("DATABASE_URL=")]
    lines.append(f"DATABASE_URL={connection_uri}")

    target.write_text("\n".join(lines) + "\n")
    return target


# ---------------------------------------------------------------------------
# Command group
# ---------------------------------------------------------------------------

@click.group("db")
def db():
    """Database setup — provision a free Neon PostgreSQL database."""
    pass


# ---------------------------------------------------------------------------
# db init
# ---------------------------------------------------------------------------

@db.command()
@click.option("--api-key", envvar="NEON_API_KEY", help="Neon API key (or set NEON_API_KEY)")
@click.option("--name", default="autowebprompt", help="Neon project name")
@click.option("--region", default="aws-us-east-2", help="Neon region")
@click.option("--env-file", default=None, help="Env file to save DATABASE_URL to")
def init(api_key, name, region, env_file):
    """Provision a Neon database and run initial migration."""
    # 1. Check for existing DATABASE_URL.
    existing_url = _load_database_url(None, env_file)
    if existing_url:
        console.print(f"[yellow]DATABASE_URL already set.[/yellow]")
        if not click.confirm("Create a new database anyway?", default=False):
            console.print("Using existing DATABASE_URL.")
            _run_migrate_inner(existing_url)
            return

    # 2. Get API key.
    if not api_key:
        api_key = click.prompt("Enter your Neon API key", hide_input=True)

    # 3. Validate key.
    console.print("Validating API key...", style="dim")
    try:
        from autowebprompt.storage.neon import NeonClient
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1)

    with NeonClient(api_key) as client:
        if not client.validate_api_key():
            console.print("[red]Invalid API key. Check your Neon dashboard for a valid key.[/red]")
            raise SystemExit(1)
        console.print("[green]API key valid.[/green]")

        # 4. Create project.
        console.print(f"Creating Neon project '{name}' in {region}...")
        try:
            project = client.create_project(name=name, region_id=region)
        except Exception as e:
            console.print(f"[red]Failed to create project: {e}[/red]")
            raise SystemExit(1)

    console.print(f"[green]Project created:[/green] {project.project_name} ({project.project_id})")

    if not project.connection_uri:
        console.print("[red]No connection URI returned. Check the Neon dashboard.[/red]")
        raise SystemExit(1)

    # 5. Test connection.
    console.print("Testing connection...", style="dim")
    from autowebprompt.storage.schema import check_connection

    if not check_connection(project.connection_uri):
        console.print("[red]Connection test failed.[/red]")
        raise SystemExit(1)
    console.print("[green]Connection OK.[/green]")

    # 6. Save to env file.
    saved_path = _save_database_url(project.connection_uri, env_file)
    console.print(f"[green]DATABASE_URL saved to {saved_path}[/green]")

    # 7. Run migration.
    _run_migrate_inner(project.connection_uri)

    console.print("\n[bold green]Database ready![/bold green] Run tasks with --fetch-from-db.")


# ---------------------------------------------------------------------------
# db migrate
# ---------------------------------------------------------------------------

@db.command()
@click.option("--database-url", envvar="DATABASE_URL", help="PostgreSQL connection string")
@click.option("--env-file", default=None, help="Env file to load DATABASE_URL from")
@click.option("--dry-run", is_flag=True, help="Print SQL without executing")
def migrate(database_url, env_file, dry_run):
    """Run schema migration (CREATE TABLE IF NOT EXISTS)."""
    if dry_run:
        from autowebprompt.storage.schema import get_migration_sql, SCHEMA_VERSION, SET_VERSION_SQL

        console.print(f"[bold]Schema version {SCHEMA_VERSION} — dry run[/bold]\n")
        for stmt in get_migration_sql():
            console.print(stmt.strip(), style="cyan")
        console.print(SET_VERSION_SQL.strip().replace("%s", f"'{SCHEMA_VERSION}'"), style="cyan")
        return

    url = _load_database_url(database_url, env_file)
    if not url:
        console.print(
            "[red]DATABASE_URL not found.[/red] Set it via --database-url, "
            "environment variable, or run `autowebprompt db init`."
        )
        raise SystemExit(1)

    _run_migrate_inner(url)


def _run_migrate_inner(database_url: str):
    """Shared migration logic."""
    from autowebprompt.storage.schema import run_migration

    console.print("Running migration...", style="dim")
    try:
        version = run_migration(database_url)
        console.print(f"[green]Migration complete — schema version {version}[/green]")
    except Exception as e:
        console.print(f"[red]Migration failed: {e}[/red]")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# db status
# ---------------------------------------------------------------------------

@db.command()
@click.option("--database-url", envvar="DATABASE_URL", help="PostgreSQL connection string")
@click.option("--env-file", default=None, help="Env file to load DATABASE_URL from")
def status(database_url, env_file):
    """Check database connection and show table status."""
    url = _load_database_url(database_url, env_file)
    if not url:
        console.print(
            "[red]DATABASE_URL not found.[/red] Set it via --database-url, "
            "environment variable, or run `autowebprompt db init`."
        )
        raise SystemExit(1)

    from autowebprompt.storage.schema import check_connection, get_table_status

    # Connection test.
    console.print("Testing connection...", style="dim")
    if not check_connection(url):
        console.print("[red]Connection failed.[/red]")
        raise SystemExit(1)
    console.print("[green]Connected.[/green]\n")

    # Table status.
    info = get_table_status(url)

    table = Table(title="Database Status")
    table.add_column("Item", style="bold")
    table.add_column("Value")

    version = info.get("schema_version") or "not set"
    table.add_row("Schema version", version)
    table.add_row("", "")

    for tbl_name, tbl_info in info["tables"].items():
        exists_str = "[green]yes[/green]" if tbl_info["exists"] else "[red]no[/red]"
        table.add_row(f"{tbl_name} exists", exists_str)
        if tbl_info["exists"]:
            table.add_row(f"{tbl_name} rows", str(tbl_info["rows"]))

    console.print(table)
