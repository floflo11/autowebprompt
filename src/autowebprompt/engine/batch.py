#!/usr/bin/env python3
"""
autowebprompt Batch Runner - Run multiple tasks through web automation sequentially.

This script orchestrates running multiple tasks through web automation providers,
supporting both Claude.ai and ChatGPT.

Usage:
    # Run tasks from a YAML file
    python -m autowebprompt.engine.batch --tasks tasks_sample.yaml

    # With custom template
    python -m autowebprompt.engine.batch --tasks tasks.yaml --template template.yaml

    # Dry run (show what would be executed)
    python -m autowebprompt.engine.batch --tasks tasks.yaml --dry-run

    # Run specific task indices
    python -m autowebprompt.engine.batch --tasks tasks.yaml --start 0 --end 5

    # Fetch task files from database (for WSP tasks)
    python -m autowebprompt.engine.batch --tasks tasks_wsp_1.yaml --fetch-from-db
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global for signal handling
_current_process = None


def _signal_handler(signum, frame):
    """Handle Ctrl+C - terminate current task."""
    global _current_process
    if _current_process:
        logger.warning("Interrupt received - terminating current task...")
        _current_process.terminate()
        try:
            _current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _current_process.kill()
    sys.exit(1)


class BatchRunner:
    """
    Orchestrates running multiple tasks through web automation providers.
    """

    # Default download directory for task files
    TASK_DOWNLOAD_DIR = Path("/tmp/claude_web_tasks")

    def __init__(
        self,
        template_path: Path = None,
        engine_script: Path = None,
        python_cmd: list = None,
        fetch_from_db: bool = False,
    ):
        """
        Initialize batch runner.

        Args:
            template_path: Path to template YAML config
            engine_script: Path to the engine runner script
            python_cmd: Python command to use (default: [sys.executable])
            fetch_from_db: If True, fetch task files from database
        """
        self.template_path = template_path
        self.template = self._load_template() if template_path else {}
        self.fetch_from_db = fetch_from_db
        self.provider = "claude"  # Default, overridden by CLI
        self.db_session = None
        self._SessionLocal = None

        # Find engine script
        if engine_script:
            self.engine_script = Path(engine_script)
        else:
            self.engine_script = Path(__file__).parent / "runner.py"

        if not self.engine_script.exists():
            raise FileNotFoundError(f"Engine script not found: {self.engine_script}")

        self.python_cmd = python_cmd or [sys.executable]

        # Initialize database connection if needed
        if fetch_from_db:
            self._init_database()

    def _init_database(self):
        """Initialize database connection."""
        try:
            from dotenv import load_dotenv
        except ImportError:
            logger.warning("python-dotenv not installed, skipping .env loading")
            load_dotenv = None

        if load_dotenv is not None:
            load_dotenv()
            env_local = Path(__file__).parents[4] / ".env.local"
            if env_local.exists():
                load_dotenv(env_local)

        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            logger.warning(
                "sqlalchemy not installed - database features disabled. "
                "Install with: pip install sqlalchemy"
            )
            self.db_session = None
            self._SessionLocal = None
            return

        try:
            from database import SessionLocal
        except ImportError:
            logger.warning(
                "database module not available - database features disabled. "
                "Ensure the database package is installed or on PYTHONPATH."
            )
            self.db_session = None
            self._SessionLocal = None
            return

        try:
            self._SessionLocal = SessionLocal
            self.db_session = SessionLocal()
            logger.info("Connected to database")
        except Exception as e:
            logger.warning(f"Failed to connect to database: {e}")
            self.db_session = None
            self._SessionLocal = None

    def _reconnect_database(self):
        """Reconnect to database after connection failure."""
        if self._SessionLocal is None:
            return False
        try:
            if self.db_session:
                try:
                    self.db_session.rollback()
                    self.db_session.close()
                except Exception:
                    pass
            self.db_session = self._SessionLocal()
            logger.info("Reconnected to database")
            return True
        except Exception as e:
            logger.warning(f"Failed to reconnect to database: {e}")
            return False

    def get_task_files_from_db(self, task_name: str, task_source: str) -> dict:
        """
        Get task starting files from database.

        Args:
            task_name: Name of the task
            task_source: Source of the task (e.g., 'wallstreetprep')

        Returns:
            Dict with 'files' (list of S3 URIs), 'found' (bool), 'deprecated' (bool or None)
        """
        result = {"files": [], "found": False, "deprecated": None, "error": None}

        if not self.db_session:
            result["error"] = "Database session not initialized"
            return result

        # Try up to 2 times (initial + 1 retry after reconnect)
        for attempt in range(2):
            try:
                from models import Task

                task = (
                    self.db_session.query(Task)
                    .filter(
                        Task.task_name == task_name,
                        Task.task_source == task_source,
                        Task.deprecated == False,  # noqa: E712
                    )
                    .first()
                )

                if task:
                    result["found"] = True
                    result["deprecated"] = task.deprecated
                    result["files"] = task.task_starting_files or []
                else:
                    # Check if task exists but is deprecated
                    deprecated_task = (
                        self.db_session.query(Task)
                        .filter(
                            Task.task_name == task_name,
                            Task.task_source == task_source,
                        )
                        .first()
                    )
                    if deprecated_task:
                        result["found"] = True
                        result["deprecated"] = deprecated_task.deprecated
                        result["error"] = f"Task '{task_name}' is deprecated"

                return result
            except Exception as e:
                error_str = str(e)
                # Check for connection-related errors
                if attempt == 0 and (
                    "SSL" in error_str
                    or "connection" in error_str.lower()
                    or "reconnect" in error_str.lower()
                ):
                    logger.warning("Database connection error, attempting reconnect...")
                    if self._reconnect_database():
                        continue  # Retry with new connection
                logger.warning(f"Failed to fetch task files from database: {e}")
                result["error"] = error_str
                return result

        return result

    def download_s3_file(self, s3_uri: str, download_dir: Path = None) -> Path:
        """
        Download a file from S3.

        Args:
            s3_uri: S3 URI (e.g., s3://bucket/path/to/file.xlsx)
            download_dir: Directory to save the file

        Returns:
            Path to downloaded file, or None if download failed
        """
        if download_dir is None:
            download_dir = self.TASK_DOWNLOAD_DIR

        download_dir.mkdir(parents=True, exist_ok=True)

        # Extract filename from S3 URI
        filename = s3_uri.split("/")[-1]
        local_path = download_dir / filename

        # Download using AWS CLI
        try:
            result = subprocess.run(
                ["aws", "s3", "cp", s3_uri, str(local_path)],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info(f"Downloaded: {s3_uri} -> {local_path}")
                return local_path
            else:
                logger.error(f"S3 download failed: {result.stderr}")
                return None
        except Exception as e:
            logger.error(f"S3 download error: {e}")
            return None

    def prepare_task_files(self, task: dict) -> dict:
        """
        Prepare task files for upload (download from S3 if needed).

        Args:
            task: Task configuration

        Returns:
            Dict with 'files' (list of local file paths), 'skip' (bool), 'skip_reason' (str or None)
        """
        result = {"files": [], "skip": False, "skip_reason": None}

        # Check if files_to_upload is already specified
        if task.get("files_to_upload"):
            result["files"] = task["files_to_upload"]
            return result

        # Try to fetch from database
        if self.fetch_from_db:
            task_name = task.get("task_name")
            task_source = task.get("task_source", "wsp")

            db_result = self.get_task_files_from_db(task_name, task_source)

            if db_result.get("error"):
                result["skip"] = True
                result["skip_reason"] = db_result["error"]
                return result

            if not db_result.get("found"):
                result["skip"] = True
                result["skip_reason"] = f"Task '{task_name}' not found in database"
                return result

            s3_files = db_result.get("files", [])

            for s3_uri in s3_files:
                local_path = self.download_s3_file(s3_uri)
                if local_path:
                    result["files"].append(str(local_path))

        return result

    def _load_template(self) -> dict:
        """Load template configuration."""
        with open(self.template_path, "r") as f:
            data = yaml.safe_load(f)
        return data.get("template", data)

    def _merge_config(self, task: dict) -> dict:
        """
        Merge task config with template.

        Args:
            task: Task-specific configuration

        Returns:
            Merged configuration dictionary
        """
        import copy

        # Start with template
        config = copy.deepcopy(self.template)

        # Override with task-specific values
        for key, value in task.items():
            if (
                isinstance(value, dict)
                and key in config
                and isinstance(config[key], dict)
            ):
                config[key].update(value)
            else:
                config[key] = value

        # Inject agent_type based on provider
        if hasattr(self, 'provider'):
            provider_map = {"claude": "claude_web", "chatgpt": "chatgpt_web"}
            config["agent_type"] = provider_map.get(self.provider, "claude_web")

        return config

    def load_tasks(self, tasks_path: Path) -> list:
        """
        Load tasks from YAML file.

        Args:
            tasks_path: Path to tasks YAML file

        Returns:
            List of task configurations
        """
        with open(tasks_path, "r") as f:
            data = yaml.safe_load(f)

        task_source = data.get("task_source", "claude_web")
        tasks = data.get("tasks", [])

        # Normalize tasks format
        normalized = []
        for task in tasks:
            if isinstance(task, str):
                # Simple task name
                normalized.append(
                    {
                        "task_name": task,
                        "task_source": task_source,
                    }
                )
            elif isinstance(task, dict):
                # Full task config
                if "task_source" not in task:
                    task["task_source"] = task_source
                normalized.append(task)

        return normalized

    def load_tasks_from_db(self, task_source: str = "wsp") -> list:
        """
        Load all non-deprecated tasks from database.

        Args:
            task_source: Task source to filter by (e.g., 'wsp', 'modeloff')

        Returns:
            List of task configurations
        """
        if not self.db_session:
            logger.error("Database session not initialized")
            return []

        # Try up to 2 times (initial + 1 retry after reconnect)
        for attempt in range(2):
            try:
                from models import Task

                try:
                    import sqlalchemy
                    from sqlalchemy import func

                    tasks = (
                        self.db_session.query(Task)
                        .filter(
                            Task.task_source == task_source,
                            Task.deprecated == False,  # noqa: E712
                            func.cast(Task.task_starting_files, sqlalchemy.Text)
                            != "[]",  # Only tasks with files
                        )
                        .order_by(Task.task_name)
                        .all()
                    )
                except ImportError:
                    logger.warning(
                        "sqlalchemy not available for advanced filtering, "
                        "using basic query"
                    )
                    tasks = (
                        self.db_session.query(Task)
                        .filter(
                            Task.task_source == task_source,
                            Task.deprecated == False,  # noqa: E712
                        )
                        .order_by(Task.task_name)
                        .all()
                    )

                normalized = []
                for task in tasks:
                    normalized.append(
                        {
                            "task_id": task.id,
                            "task_name": task.task_name,
                            "task_source": task.task_source,
                        }
                    )

                logger.info(
                    f"Loaded {len(normalized)} tasks from database (source: {task_source})"
                )
                return normalized

            except Exception as e:
                error_str = str(e)
                if attempt == 0 and (
                    "SSL" in error_str
                    or "connection" in error_str.lower()
                    or "reconnect" in error_str.lower()
                ):
                    logger.warning("Database connection error, attempting reconnect...")
                    if self._reconnect_database():
                        continue
                logger.error(f"Failed to load tasks from database: {e}")
                return []

        return []

    def run_task(
        self,
        task: dict,
        task_index: int,
        dry_run: bool = False,
        keep_temp_configs: bool = False,
        timeout: int = None,
    ) -> bool:
        """
        Run a single task.

        Args:
            task: Task configuration
            task_index: Task index (for logging)
            dry_run: If True, just print what would be executed
            keep_temp_configs: If True, don't delete temp config files
            timeout: Task timeout in seconds

        Returns:
            True if task succeeded
        """
        global _current_process

        task_name = task.get("task_name", f"task_{task_index}")
        logger.info(f"\n{'='*60}")
        logger.info(f"TASK {task_index}: {task_name}")
        logger.info(f"{'='*60}")

        # Prepare task files (download from S3 if needed)
        if self.fetch_from_db:
            prep_result = self.prepare_task_files(task)
            if prep_result.get("skip"):
                logger.warning(
                    f"Skipping task {task_name}: {prep_result['skip_reason']}"
                )
                return False
            files_to_upload = prep_result.get("files", [])
            if files_to_upload:
                task["files_to_upload"] = files_to_upload
                logger.info(f"Prepared {len(files_to_upload)} file(s) for upload")

        # Merge with template
        config = self._merge_config(task)

        # Create temp config file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", prefix=f"claude_web_{task_name}_", delete=False
        ) as f:
            yaml.dump(config, f, default_flow_style=False)
            temp_config_path = f.name

        try:
            # Build command
            cmd = [
                *self.python_cmd,
                str(self.engine_script),
                "--config",
                temp_config_path,
                "--no-hold",
            ]

            if dry_run:
                logger.info(f"[DRY RUN] Would execute: {' '.join(cmd)}")
                logger.info(f"Config:\n{yaml.dump(config, default_flow_style=False)}")
                return True

            logger.info(f"Executing: {' '.join(cmd)}")

            # Run task
            _current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            # Stream output
            try:
                for line in iter(_current_process.stdout.readline, ""):
                    print(line, end="", flush=True)
            except Exception:
                pass

            # Wait for completion
            try:
                return_code = _current_process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.error(f"Task {task_name} timed out after {timeout}s")
                _current_process.terminate()
                try:
                    _current_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _current_process.kill()
                return False

            _current_process = None

            if return_code == 0:
                logger.info(f"Task {task_name} completed successfully")
                return True
            else:
                logger.error(
                    f"Task {task_name} failed with return code {return_code} "
                    f"(engine handles retries internally)"
                )
                return False

        finally:
            # Clean up temp config
            if not keep_temp_configs:
                try:
                    os.unlink(temp_config_path)
                except Exception:
                    pass

    def run_all_tasks(
        self,
        tasks: list,
        dry_run: bool = False,
        start_index: int = 0,
        end_index: int = None,
        continue_on_failure: bool = True,
        default_timeout: int = None,
    ) -> dict:
        """
        Run all tasks sequentially.

        Args:
            tasks: List of task configurations
            dry_run: If True, just print what would be executed
            start_index: Start from this task index
            end_index: Stop at this task index (exclusive)
            continue_on_failure: Continue running tasks even if one fails
            default_timeout: Default timeout per task in seconds

        Returns:
            Dict with results summary
        """
        if end_index is None:
            end_index = len(tasks)

        tasks_to_run = tasks[start_index:end_index]
        logger.info(
            f"Running {len(tasks_to_run)} tasks (indices {start_index}-{end_index-1})"
        )

        results = {
            "total": len(tasks_to_run),
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "tasks": [],
        }

        for i, task in enumerate(tasks_to_run):
            task_index = start_index + i
            task_name = task.get("task_name", f"task_{task_index}")

            # Get timeout
            timeout = task.get("timeout", default_timeout)
            if timeout is None:
                timeout = task.get("claude_web", {}).get("max_sec_per_task")

            start_time = datetime.now()

            try:
                success = self.run_task(
                    task=task,
                    task_index=task_index,
                    dry_run=dry_run,
                    timeout=timeout,
                )
            except KeyboardInterrupt:
                logger.warning("Interrupted by user")
                results["skipped"] += len(tasks_to_run) - i - 1
                break
            except Exception as e:
                logger.error(f"Task {task_name} failed with exception: {e}")
                success = False

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            results["tasks"].append(
                {
                    "task_name": task_name,
                    "index": task_index,
                    "success": success,
                    "duration_seconds": duration,
                }
            )

            if success:
                results["succeeded"] += 1
            else:
                results["failed"] += 1
                if not continue_on_failure:
                    logger.error("Stopping due to failure (--stop-on-failure)")
                    results["skipped"] += len(tasks_to_run) - i - 1
                    break

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="autowebprompt Batch Runner - Run multiple tasks through web automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tasks",
        required=False,
        help="Path to tasks YAML file (not required when using --from-db)",
    )
    parser.add_argument(
        "--template",
        default=None,
        help="Path to template YAML file (default: tasks_configs/template_claude_web.yaml)",
    )
    parser.add_argument(
        "--provider",
        choices=["claude", "chatgpt"],
        default="claude",
        help="Web automation provider: 'claude' (default) or 'chatgpt'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be executed without running",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="Start from this task index",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=None,
        help="Stop at this task index (exclusive)",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop running if a task fails",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="Default timeout per task in seconds",
    )
    parser.add_argument(
        "--fetch-from-db",
        action="store_true",
        help="Fetch task files from database and S3 (required for WSP tasks)",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Load task list from database instead of YAML file",
    )
    parser.add_argument(
        "--source",
        type=str,
        default="wsp",
        help="Task source when loading from database (default: wsp)",
    )
    args = parser.parse_args()

    # Signal handler
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        # Find template (provider-aware default)
        if not args.template:
            template_defaults = {
                "claude": "tasks_configs/template_claude_web.yaml",
                "chatgpt": "tasks_configs/template_chatgpt_web.yaml",
            }
            default_template_rel = template_defaults.get(args.provider, "tasks_configs/template_claude_web.yaml")
            default_template = Path(__file__).parent / default_template_rel
            if default_template.exists():
                args.template = str(default_template)

        template_path = args.template

        if template_path:
            template_path = Path(template_path)
            if not template_path.exists():
                logger.error(f"Template not found: {template_path}")
                sys.exit(1)

        # Determine if we're loading from database
        from_db = getattr(args, "from_db", False)

        # Validate args
        if not from_db and not args.tasks:
            logger.error("Either --tasks or --from-db must be specified")
            sys.exit(1)

        # When loading from db, always fetch files from db too
        fetch_from_db = args.fetch_from_db or from_db

        # Initialize runner
        runner = BatchRunner(
            template_path=template_path,
            fetch_from_db=fetch_from_db,
        )
        runner.provider = args.provider

        # Load tasks
        if from_db:
            # Load tasks from database
            task_source = args.source
            tasks = runner.load_tasks_from_db(task_source)
            if not tasks:
                logger.error(f"No tasks found in database for source: {task_source}")
                sys.exit(1)
            logger.info(
                f"Loaded {len(tasks)} tasks from database (source: {task_source})"
            )
        else:
            # Load tasks from YAML file
            tasks_path = Path(args.tasks)
            if not tasks_path.exists():
                logger.error(f"Tasks file not found: {tasks_path}")
                sys.exit(1)
            tasks = runner.load_tasks(tasks_path)
            logger.info(f"Loaded {len(tasks)} tasks from {tasks_path}")

        # Run tasks
        results = runner.run_all_tasks(
            tasks=tasks,
            dry_run=args.dry_run,
            start_index=args.start,
            end_index=args.end,
            continue_on_failure=not args.stop_on_failure,
            default_timeout=args.timeout,
        )

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("BATCH RUN COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Total:     {results['total']}")
        logger.info(f"Succeeded: {results['succeeded']}")
        logger.info(f"Failed:    {results['failed']}")
        logger.info(f"Skipped:   {results['skipped']}")

        # Save results
        results_file = Path("claude_web_batch_results.json")
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        logger.info(f"Results saved to: {results_file}")

        # Exit code
        if results["failed"] > 0:
            sys.exit(1)
        sys.exit(0)

    except Exception as e:
        logger.error(f"Batch runner failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
