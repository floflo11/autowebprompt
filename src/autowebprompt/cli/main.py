"""CLI entry point for autowebprompt."""

import click

from autowebprompt import __version__


@click.group()
@click.version_option(version=__version__, prog_name="autowebprompt")
def cli():
    """autowebprompt — Automate ChatGPT and Claude web UIs with Playwright."""
    pass


@cli.command()
def setup():
    """Interactive setup wizard — configure your first automation."""
    from autowebprompt.cli.wizard import run_wizard
    run_wizard()


@cli.command()
@click.option("--tasks", type=click.Path(exists=True), help="YAML task file")
@click.option("--template", type=click.Path(exists=True), help="Template YAML config")
@click.option(
    "--provider",
    type=click.Choice(["claude", "chatgpt"]),
    required=True,
    help="AI provider to automate",
)
@click.option("--csv", "csv_file", type=click.Path(exists=True), help="CSV task file (alternative to YAML)")
@click.option("--task", type=str, help="Single task name")
@click.option("--files", type=str, multiple=True, help="Files for single task mode")
@click.option("--fetch-from-db", is_flag=True, help="Fetch task files from database")
@click.option("--dry-run", is_flag=True, help="Show what would run without executing")
@click.option("--start", type=int, default=0, help="Start from this task index")
@click.option("--end", type=int, default=None, help="Stop at this task index")
@click.option("--timeout", type=int, default=None, help="Timeout per task in seconds")
def run(tasks, template, provider, csv_file, task, files, fetch_from_db, dry_run, start, end, timeout):
    """Run automation tasks against ChatGPT or Claude."""
    from autowebprompt.engine.batch import BatchRunner

    try:
        runner = BatchRunner(
            template_path=template,
            fetch_from_db=fetch_from_db,
        )
        runner.provider = provider

        if tasks:
            task_list = runner.load_tasks(tasks)
        else:
            click.echo("Error: --tasks is required", err=True)
            raise SystemExit(1)

        results = runner.run_all_tasks(
            tasks=task_list,
            dry_run=dry_run,
            start_index=start,
            end_index=end,
            default_timeout=timeout,
        )

        # Print summary
        click.echo(f"\n{'='*50}")
        click.echo("BATCH COMPLETE")
        click.echo(f"{'='*50}")
        click.echo(f"Total:     {results['total']}")
        click.echo(f"Succeeded: {results['succeeded']}")
        click.echo(f"Failed:    {results['failed']}")
        click.echo(f"Skipped:   {results['skipped']}")

        if results["failed"] > 0:
            raise SystemExit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@cli.command()
@click.option("--port", type=int, default=9222, help="CDP port to check")
def check(port):
    """Check if Chrome is running with CDP and ready for automation."""
    from autowebprompt.browser.manager import is_cdp_available, find_chrome

    chrome_path = find_chrome()
    if chrome_path:
        click.echo(f"Chrome found: {chrome_path}")
    else:
        click.echo("Chrome not found! Please install Chrome or Chrome Canary.", err=True)
        raise SystemExit(1)

    if is_cdp_available(port):
        click.echo(f"Chrome CDP is running on port {port}")
    else:
        click.echo(f"Chrome CDP is NOT running on port {port}", err=True)
        click.echo(f"\nStart Chrome with CDP:")
        click.echo(f'  "{chrome_path}" --remote-debugging-port={port} --user-data-dir=~/.autowebprompt-chrome-profile')
        raise SystemExit(1)

    click.echo("\nReady for automation!")


from autowebprompt.cli.db import db as db_group
cli.add_command(db_group)


@cli.command()
def templates():
    """Show example template configurations."""
    import importlib.resources as pkg_resources

    click.echo("Example templates are installed with the package.")
    click.echo("\nTo copy a template to your project:")
    click.echo("  autowebprompt setup")
    click.echo("\nOr manually create from the examples in:")
    click.echo("  autowebprompt/config/templates/")


if __name__ == "__main__":
    cli()
