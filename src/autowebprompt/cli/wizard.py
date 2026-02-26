"""Interactive setup wizard for autowebprompt."""

import shutil
from pathlib import Path

import click


def run_wizard():
    """Walk the user through first-time setup."""
    click.echo("\n=== autowebprompt Setup Wizard ===\n")

    # Step 1: Choose provider
    provider = click.prompt(
        "Which AI provider do you want to automate?",
        type=click.Choice(["claude", "chatgpt"]),
        default="chatgpt",
    )

    # Step 2: Copy template
    templates_dir = Path(__file__).parent.parent / "config" / "templates"
    template_name = f"template_{provider}.yaml"
    template_src = templates_dir / template_name

    dest_dir = Path.cwd()
    template_dest = dest_dir / template_name

    if template_dest.exists():
        overwrite = click.confirm(
            f"{template_dest.name} already exists. Overwrite?", default=False
        )
        if not overwrite:
            click.echo("Keeping existing template.")
        else:
            shutil.copy2(template_src, template_dest)
            click.echo(f"Copied template to {template_dest}")
    else:
        shutil.copy2(template_src, template_dest)
        click.echo(f"Copied template to {template_dest}")

    # Step 3: Copy example tasks
    tasks_src = templates_dir / "example_tasks.yaml"
    tasks_dest = dest_dir / "tasks.yaml"

    if not tasks_dest.exists():
        shutil.copy2(tasks_src, tasks_dest)
        click.echo(f"Copied example tasks to {tasks_dest}")

    # Step 4: Project ID
    click.echo(f"\nNext steps:")
    click.echo(f"  1. Edit {template_dest.name} — set your project ID")
    if provider == "chatgpt":
        click.echo(
            "     Find it at: https://chatgpt.com/g/g-p-YOUR_ID-name/project"
        )
    else:
        click.echo("     Find it at: https://claude.ai/project/YOUR_ID")

    click.echo(f"  2. Edit tasks.yaml — list the tasks you want to run")
    click.echo(f"  3. Start Chrome with CDP:")
    click.echo(
        f'     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\'
    )
    click.echo(f"       --remote-debugging-port=9222 \\")
    click.echo(f"       --user-data-dir=~/.autowebprompt-chrome-profile")
    click.echo(f"  4. Log into {provider}.com in that browser")
    click.echo(f"  5. Run:")
    click.echo(
        f"     autowebprompt run --provider {provider} "
        f"--tasks tasks.yaml --template {template_dest.name}"
    )
    click.echo()
