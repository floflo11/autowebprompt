#!/usr/bin/env python3
"""
autowebprompt Engine Runner - Automate tasks through web-based AI interfaces.

This is the main entry point for running tasks through web AI providers
(Claude.ai, ChatGPT, etc.).

Workflow:
1. Load config (with hierarchical overrides)
2. Two-tier retry loop:
   a. Pipeline phase: launch browser, navigate, auth, upload files
   b. Agent phase: process prompts, download artifacts, validate
3. Save results (JSON logs + solution files) in date-organized folders
4. Optionally upload to S3 / database

Usage:
    # Standalone
    python -m autowebprompt.engine.runner --config config.yaml

    # Batch automation
    python claude_web_batch_runner.py --tasks tasks.yaml --template template_claude_web.yaml

    # Non-interactive mode
    python -m autowebprompt.engine.runner --config config.yaml --no-hold
"""

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from autowebprompt.agents.claude import ClaudeWebAgent
from autowebprompt.agents.chatgpt import ChatGPTWebAgent
from autowebprompt.agents.base import WebAgent, AgentState
from autowebprompt.browser.manager import BrowserManager
from autowebprompt.engine.completion_logger import CompletionLogger
from autowebprompt.validators.excel import validate_excel_file
from autowebprompt.storage.uploader import ResultUploader
from autowebprompt.agents.base import PipelineError, TaskStatus

# Initialize logger
logger = logging.getLogger(__name__)

# Global shutdown event
shutdown_event = asyncio.Event()


def _handle_signal(signum, frame):
    """Handle shutdown signals gracefully."""
    try:
        shutdown_event.set()
    except Exception:
        pass
    signal.signal(signal.SIGINT, signal.SIG_DFL)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def create_run_directory(
    base_dir: str | Path, folder_prefix: str = "claudeGUI"
) -> Path:
    """
    Create date-organized output directory.

    Structure:
        {YYYYMMDD}_{folder_prefix}/
        |- solutions/
        |- json_logs/

    Returns the run_dir Path ({YYYYMMDD}_{folder_prefix}/).
    """
    base_dir = Path(base_dir)
    date_str = datetime.now().strftime("%Y%m%d")
    run_dir = base_dir / f"{date_str}_{folder_prefix}"
    (run_dir / "solutions").mkdir(parents=True, exist_ok=True)
    (run_dir / "json_logs").mkdir(parents=True, exist_ok=True)
    return run_dir


def rename_solution_file(
    file_path: str | Path,
    task_name: str,
    agent_name: str = "claude_web",
) -> Path:
    """
    Rename a downloaded solution file to match upload_tabai_folder.py regex.

    Target pattern (Pattern 2):
        {YYYYMMDD}_{HHMMSS}_{task_name}_Solution_{agent}_Model.xlsx

    Returns the new file path.
    """
    file_path = Path(file_path)
    safe_task = task_name.replace("/", "-").replace(" ", "_")
    safe_task = re.sub(r"[^a-zA-Z0-9._-]", "", safe_task)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{timestamp}_{safe_task}_Solution_{agent_name}_Model{file_path.suffix}"
    new_path = file_path.parent / new_name

    # Handle collision
    counter = 1
    while new_path.exists():
        stem = f"{timestamp}_{safe_task}_Solution_{agent_name}_Model_{counter}"
        new_path = file_path.parent / f"{stem}{file_path.suffix}"
        counter += 1

    shutil.move(str(file_path), str(new_path))
    logger.info(f"Renamed solution: {file_path.name} -> {new_path.name}")
    return new_path


def mark_json_deprecated(
    json_path: str | Path, reason: str = "Superseded by later attempt"
):
    """Mark a completion JSON as deprecated by updating it on disk."""
    json_path = Path(json_path)
    if not json_path.exists():
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
        for task in data.get("tasks", []):
            task["deprecated"] = True
            task["deprecated_reason"] = reason
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Marked as deprecated: {json_path.name}")
    except Exception as e:
        logger.warning(f"Failed to mark JSON deprecated: {e}")


async def _cleanup_browser(browser_mgr, context, browser, page):
    """Best-effort browser cleanup."""
    try:
        if page:
            await page.close()
    except Exception:
        pass
    try:
        if browser_mgr and context and browser:
            await browser_mgr.close_browser(context, browser)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Logging setup + config loading (unchanged)
# ---------------------------------------------------------------------------


def setup_logging(config: dict, name: str, task_name: str = None) -> tuple:
    """Setup logging with optional file output."""
    _, agent_config = get_provider_config(config)
    log_config = agent_config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO").upper())
    save_to_file = log_config.get("save_to_file", True)
    log_directory = log_config.get("log_directory", "claude_web_logs")

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    root_logger.addHandler(console_handler)

    log_file_path = None

    if save_to_file:
        # Create log directory
        log_dir = Path(log_directory)
        log_dir.mkdir(parents=True, exist_ok=True)

        # Create log file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task_name = (
            task_name.replace("/", "_").replace("\\", "_") if task_name else "unknown"
        )
        log_filename = f"claude_web_{timestamp}_{safe_task_name}.log"
        log_file_path = log_dir / log_filename

        file_handler = logging.FileHandler(log_file_path)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root_logger.addHandler(file_handler)

    return logging.getLogger(name), log_file_path


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    import yaml

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Handle template nesting
    if "template" in config:
        config = config["template"]

    return config


def get_provider_config(config: dict) -> tuple[str, dict]:
    """
    Determine provider from config and return (provider_key, agent_config).
    provider_key is 'claude_web' or 'chatgpt_web'.
    """
    agent_type = config.get("agent_type", "claude_web")
    if agent_type == "chatgpt_web":
        return "chatgpt_web", config.get("chatgpt_web", {})
    return "claude_web", config.get("claude_web", {})


def create_agent(provider_key: str, page, config: dict, shutdown_event=None, completion_logger=None) -> WebAgent:
    """Factory: create the right WebAgent subclass based on provider."""
    if provider_key == "chatgpt_web":
        return ChatGPTWebAgent(page=page, config=config, shutdown_event=shutdown_event, completion_logger=completion_logger)
    return ClaudeWebAgent(page=page, config=config, shutdown_event=shutdown_event, completion_logger=completion_logger)


PROVIDER_DEFAULTS = {
    "claude_web": {
        "folder_prefix": "claudeGUI",
        "agent_name": "claude_web",
        "agent_model_name": "Opus 4.5",
        "agent_model_type": "gui",
        "s3_artifact_prefix": "attempts/claude_web",
        "s3_conversation_prefix": "claude_web_conversations",
    },
    "chatgpt_web": {
        "folder_prefix": "chatgptGUI",
        "agent_name": "chatgpt_web",
        "agent_model_name": "GPT-5.2",
        "agent_model_type": "gui",
        "s3_artifact_prefix": "attempts/chatgpt_web",
        "s3_conversation_prefix": "chatgpt_web_conversations",
    },
}


# ---------------------------------------------------------------------------
# Main automation with two-tier retry loop
# ---------------------------------------------------------------------------


async def run_automation(config: dict) -> bool:
    """
    Main automation entry point with two-tier retry loop.

    Phase 1 (Pipeline): Browser launch, navigation, auth, file upload.
        Failures here are infrastructure issues -- no JSON created, no agent_attempts.

    Phase 2 (Agent): Prompt processing, download, validation.
        Failures here are the agent's fault -- JSON created, agent_attempts incremented.

    Args:
        config: Configuration dictionary

    Returns:
        True if automation succeeded
    """
    no_hold = "--no-hold" in sys.argv

    # ---- Provider detection ----
    provider_key, agent_config = get_provider_config(config)
    provider_defaults = PROVIDER_DEFAULTS.get(provider_key, PROVIDER_DEFAULTS["claude_web"])

    # Allow config to override default model names
    provider_defaults = dict(provider_defaults)  # shallow copy so we don't mutate the module-level dict
    if "agent_model_name" in agent_config:
        provider_defaults["agent_model_name"] = agent_config["agent_model_name"]
    if "agent_model_type" in agent_config:
        provider_defaults["agent_model_type"] = agent_config["agent_model_type"]

    logger.info(f"Provider: {provider_key}")

    # ---- Config extraction ----
    retry_config = agent_config.get("retry", {})
    output_config = agent_config.get("output", {})
    session_config = agent_config.get("session", {})

    max_agent_attempts = retry_config.get("max_agent_attempts", 3)
    max_total_attempts = retry_config.get("max_total_attempts", 10)
    max_sec_per_task = retry_config.get(
        "max_sec_per_task",
        agent_config.get("max_sec_per_task", 0),
    )
    max_sec_per_attempt = retry_config.get("max_sec_per_attempt", 1800)
    sleep_between_retries = retry_config.get("sleep_between_retries", 5)

    base_dir = Path(output_config.get("base_dir", "."))
    folder_prefix = output_config.get("folder_prefix", provider_defaults["folder_prefix"])

    agent_name = session_config.get("agent_name", provider_defaults["agent_name"])
    prompt_version = session_config.get("prompt_version", 1)

    task_id = config.get("task_id")
    task_name = config.get("task_name", "unnamed_task")
    task_source = config.get("task_source", "claude_web")
    files_to_upload = config.get("files_to_upload", [])

    if max_sec_per_task > 0:
        logger.info(f"Task timeout: {max_sec_per_task}s ({max_sec_per_task // 60}m)")
    else:
        logger.info("No timeout (unlimited runtime)")

    logger.info(f"Task: {task_name} (ID: {task_id})")
    logger.info(f"Source: {task_source}")
    logger.info(
        f"Retry config: max_agent={max_agent_attempts}, max_total={max_total_attempts}"
    )

    # ---- Create date-organized output dirs ----
    run_dir = create_run_directory(base_dir, folder_prefix)
    solutions_dir = run_dir / "solutions"
    json_logs_dir = run_dir / "json_logs"
    logger.info(f"Output directory: {run_dir}")

    # ---- Retry loop ----
    agent_attempts = 0
    total_attempts = 0
    agent_json_paths: list[Path] = []
    task_wall_start = time.time()
    task_success = False

    while True:
        # Check termination conditions
        if total_attempts >= max_total_attempts:
            logger.error(f"Max total attempts ({max_total_attempts}) exhausted")
            break
        if agent_attempts >= max_agent_attempts:
            logger.error(f"Max agent attempts ({max_agent_attempts}) exhausted")
            break
        if max_sec_per_task > 0 and (time.time() - task_wall_start) >= max_sec_per_task:
            logger.error(f"Wall-clock budget ({max_sec_per_task}s) exhausted")
            break
        if shutdown_event.is_set():
            logger.warning("Shutdown signal received, exiting retry loop")
            break

        total_attempts += 1
        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"ATTEMPT {total_attempts} (agent_attempts={agent_attempts}/{max_agent_attempts})"
        )
        logger.info(f"{'=' * 60}")

        browser = None
        context = None
        page = None
        browser_mgr = None
        completion_logger = None

        # =====================================================================
        # PHASE 1: Pipeline (no JSON created, no agent_attempts counted)
        # =====================================================================
        try:
            browser_mgr = BrowserManager(config)
            playwright_ctx = async_playwright()
            playwright = await playwright_ctx.__aenter__()

            try:
                browser, context = await browser_mgr.launch_browser(playwright)
                # Close stale pages from previous attempts, then create a fresh page.
                # NOTE: Do NOT call set_viewport_size on CDP pages -- it uses
                # Emulation.setDeviceMetricsOverride which crashes ChatGPT tabs.
                for stale in context.pages:
                    try:
                        await stale.close()
                    except Exception:
                        pass
                page = await context.new_page()
                logger.info("Created new browser page")

                agent = create_agent(
                    provider_key,
                    page=page,
                    config=config,
                    shutdown_event=shutdown_event,
                    completion_logger=None,
                )

                # Navigate
                provider_name = "ChatGPT" if provider_key == "chatgpt_web" else "Claude.ai"
                if not await agent.navigate_to_new_chat():
                    raise PipelineError(
                        TaskStatus.NAVIGATION_FAILED, f"Failed to navigate to {provider_name}"
                    )

                # Auth check
                state = await agent.get_state()
                logger.info(f"{provider_name} state: {state.value}")

                if state == AgentState.AUTH_REQUIRED:
                    logger.info(
                        "Authentication required -- waiting for login (max 5 min)..."
                    )
                    login_timeout = 300
                    elapsed = 0
                    while elapsed < login_timeout:
                        await asyncio.sleep(10)
                        elapsed += 10
                        # After auth redirect, try lightweight navigation back
                        current_url = page.url
                        if "chatgpt.com" not in current_url and "claude.ai" not in current_url:
                            if elapsed % 30 == 0:
                                logger.info(f"Still on auth page ({current_url[:60]}...), retrying navigation...")
                            try:
                                await page.goto(agent.project_url if hasattr(agent, 'project_url') else "https://chatgpt.com",
                                                wait_until="domcontentloaded", timeout=15000)
                                await page.wait_for_timeout(2000)
                            except Exception:
                                pass
                        state = await agent.get_state()
                        if state == AgentState.READY:
                            logger.info("Login successful!")
                            await browser_mgr.save_auth_state(context)
                            break
                        if elapsed % 30 == 0:
                            logger.info(f"Still waiting for login... ({elapsed}s / {login_timeout}s)")

                    if state != AgentState.READY:
                        raise PipelineError(TaskStatus.AUTH_FAILED, "Login timeout")

                if state == AgentState.RATE_LIMITED:
                    raise PipelineError(
                        TaskStatus.RATE_LIMITED, "Rate limited before prompts"
                    )

                # Agent mode is now enabled inside submit_prompt() --
                # after files are attached and prompt is typed, before send.

                # Upload files (in Phase 1 so they're ready for Phase 2)
                if files_to_upload:
                    logger.info(f"Uploading {len(files_to_upload)} file(s)...")
                    if not await agent.upload_files(files_to_upload):
                        raise PipelineError(
                            TaskStatus.UPLOAD_FAILED, "File upload failed"
                        )

            except PipelineError:
                # Close playwright before re-raising
                await _cleanup_browser(browser_mgr, context, browser, page)
                await playwright_ctx.__aexit__(None, None, None)
                raise

        except PipelineError as e:
            logger.warning(f"Pipeline failure ({e.status.value}): {e}")
            logger.info(f"Retrying in {sleep_between_retries}s...")
            await asyncio.sleep(sleep_between_retries)
            continue

        # =====================================================================
        # PHASE 2: Agent (JSON created, attempt counted)
        # =====================================================================
        try:
            # Create completion logger for this attempt
            completion_logger = CompletionLogger(
                log_dir=str(json_logs_dir),
                task_identifier=task_name,
                agent_name=agent_name,
                prompt_version=prompt_version,
                task_source=task_source,
            )
            completion_logger.start_task(task_name, attempt_number=total_attempts)

            # Wire logger into agent
            agent.completion_logger = completion_logger

            # Set up per-attempt timeout
            attempt_timed_out = False

            async def _attempt_timeout_guard():
                nonlocal attempt_timed_out
                effective_timeout = max_sec_per_attempt
                if max_sec_per_task > 0:
                    remaining = max_sec_per_task - (time.time() - task_wall_start)
                    effective_timeout = min(effective_timeout, remaining)
                if effective_timeout > 0:
                    await asyncio.sleep(effective_timeout)
                    attempt_timed_out = True
                    shutdown_event.set()

            guard_task = asyncio.create_task(_attempt_timeout_guard())

            try:
                # Process prompts (files already uploaded in Phase 1)
                prompt_success = await agent.process_all_prompts(files_to_upload=[])

                if not prompt_success:
                    if attempt_timed_out:
                        status = TaskStatus.TIMEOUT
                    else:
                        status = TaskStatus.PROMPT_FAILED
                    agent_attempts += 1
                    completion_logger.end_task(status)
                    agent_json_paths.append(completion_logger.session_file)
                    logger.warning(f"Agent failure: {status.value}")

                    # Best-effort archival download
                    try:
                        await agent.download_all_artifacts(
                            download_dir=str(solutions_dir)
                        )
                    except Exception:
                        pass

                    try:
                        await _cleanup_browser(browser_mgr, context, browser, page)
                        await playwright_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass

                    await asyncio.sleep(sleep_between_retries)
                    continue

                # Prompt succeeded -- download artifacts
                logger.info("All prompts completed! Downloading artifacts...")
                downloaded_files = await agent.download_all_artifacts(
                    download_dir=str(solutions_dir)
                )

                if not downloaded_files:
                    agent_attempts += 1
                    completion_logger.end_task(TaskStatus.DOWNLOAD_FAILED)
                    agent_json_paths.append(completion_logger.session_file)
                    logger.warning("Download failed -- no artifacts retrieved")

                    try:
                        await _cleanup_browser(browser_mgr, context, browser, page)
                        await playwright_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    await asyncio.sleep(sleep_between_retries)
                    continue

                # Validate downloaded files
                excel_files = [
                    f for f in downloaded_files if f.lower().endswith((".xlsx", ".xls"))
                ]
                if not excel_files:
                    agent_attempts += 1
                    completion_logger.end_task(TaskStatus.DOWNLOAD_FAILED)
                    agent_json_paths.append(completion_logger.session_file)
                    logger.warning(
                        f"No Excel files among {len(downloaded_files)} downloaded file(s)"
                    )
                    try:
                        await _cleanup_browser(browser_mgr, context, browser, page)
                        await playwright_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    await asyncio.sleep(sleep_between_retries)
                    continue

                validation_failed = False
                for fpath in excel_files:
                    is_valid, val_status, val_msg = validate_excel_file(fpath)
                    if not is_valid:
                        agent_attempts += 1
                        completion_logger.end_task(val_status)
                        agent_json_paths.append(completion_logger.session_file)
                        logger.warning(
                            f"Validation failed ({val_status.value}): {val_msg}"
                        )
                        validation_failed = True
                        break

                if validation_failed:
                    try:
                        await _cleanup_browser(browser_mgr, context, browser, page)
                        await playwright_ctx.__aexit__(None, None, None)
                    except Exception:
                        pass
                    await asyncio.sleep(sleep_between_retries)
                    continue

                # Rename solution files to match upload_tabai_folder.py pattern
                renamed_files = []
                for fpath in downloaded_files:
                    if fpath.lower().endswith((".xlsx", ".xls")):
                        new_path = rename_solution_file(fpath, task_name, agent_name)
                        renamed_files.append(str(new_path))
                    else:
                        renamed_files.append(fpath)

                # SUCCESS
                agent_attempts += 1
                completion_logger.end_task(TaskStatus.SUCCESS)
                agent_json_paths.append(completion_logger.session_file)
                logger.info("Task completed successfully!")

                # Save conversation history
                history = await agent.get_conversation_history()
                default_log_dir = "chatgpt_web_logs" if provider_key == "chatgpt_web" else "claude_web_logs"
                log_dir = Path(
                    agent_config.get("logging", {}).get(
                        "log_directory", default_log_dir
                    )
                )
                history_dir = log_dir / "conversations"
                history_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                history_file = (
                    history_dir / f"conversation_{timestamp}_{task_name}.json"
                )
                with open(history_file, "w") as f:
                    json.dump(
                        {
                            "task_name": task_name,
                            "task_source": task_source,
                            "timestamp": datetime.now().isoformat(),
                            "messages": history,
                        },
                        f,
                        indent=2,
                    )
                logger.info(f"Saved conversation to: {history_file}")

                # Upload to S3 and database if configured
                upload_to_cloud = config.get("upload_to_cloud", False)
                if upload_to_cloud:
                    logger.info("Uploading results to S3 and database...")
                    upload_config = {
                        **config,
                        "s3_bucket": config.get(
                            "s3_bucket", os.environ.get("AWS_S3_BUCKET", "")
                        ),
                        "db_enabled": config.get("db_enabled", True),
                        "agent_model_name": provider_defaults["agent_model_name"],
                        "agent_model_type": provider_defaults["agent_model_type"],
                        "s3_artifact_prefix": provider_defaults["s3_artifact_prefix"],
                        "s3_conversation_prefix": provider_defaults["s3_conversation_prefix"],
                    }
                    uploader = ResultUploader(upload_config)

                    task_start_time = None
                    if history:
                        first_msg_time = history[0].get("timestamp")
                        if first_msg_time:
                            try:
                                task_start_time = datetime.fromisoformat(first_msg_time)
                            except Exception:
                                pass
                    if not task_start_time:
                        task_start_time = completion_logger.session_start

                    upload_result = uploader.upload_results(
                        task_id=task_id,
                        task_name=task_name,
                        task_source=task_source,
                        artifact_paths=renamed_files,
                        conversation_history=history,
                        start_time=task_start_time,
                        end_time=datetime.now(),
                        additional_metadata={
                            "config_file": str(config.get("_config_path", "unknown")),
                            "prompts_count": len(config.get("prompts", [])),
                            "files_uploaded": len(files_to_upload),
                        },
                    )

                    if upload_result["success"]:
                        logger.info("Upload successful!")
                        logger.info(
                            f"  Artifact S3 URIs: {upload_result['artifact_s3_uris']}"
                        )
                        logger.info(
                            f"  Conversation S3 URI: {upload_result['conversation_s3_uri']}"
                        )
                        logger.info(f"  TaskAttempt ID: {upload_result['attempt_id']}")
                    else:
                        logger.warning(
                            f"Upload completed with errors: {upload_result['errors']}"
                        )

                # Hold browser open unless --no-hold
                if not no_hold:
                    logger.info("Browser staying open for inspection...")
                    logger.info("Press Ctrl+C to exit")
                    while not shutdown_event.is_set():
                        await asyncio.sleep(1)

                await _cleanup_browser(browser_mgr, context, browser, page)
                await playwright_ctx.__aexit__(None, None, None)
                task_success = True
                break  # Done

            finally:
                guard_task.cancel()
                # Reset shutdown for potential next attempt
                if attempt_timed_out:
                    shutdown_event.clear()

        except Exception as e:
            logger.error(f"Unexpected error in Phase 2: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            agent_attempts += 1
            if completion_logger and completion_logger.current_task:
                completion_logger.end_task(TaskStatus.UNKNOWN)
                agent_json_paths.append(completion_logger.session_file)
            await _cleanup_browser(browser_mgr, context, browser, page)
            try:
                await playwright_ctx.__aexit__(None, None, None)
            except Exception:
                pass
            await asyncio.sleep(sleep_between_retries)
            continue

    # ---- Post-loop: deprecate earlier agent JSONs ----
    if len(agent_json_paths) > 1:
        for path in agent_json_paths[:-1]:
            mark_json_deprecated(path, "Superseded by later attempt")

    if not task_success:
        logger.error(
            f"Task failed after {total_attempts} total attempts "
            f"({agent_attempts} agent attempts)"
        )

    return task_success


def main():
    """Main entry point."""
    # CLI Arguments
    parser = argparse.ArgumentParser(
        description="autowebprompt Engine Runner - Automate tasks through web AI interfaces",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python -m autowebprompt.engine.runner --config config.yaml

  # Batch mode
  python -m autowebprompt.engine.runner --config config.yaml --no-hold

  # With timeout
  python -m autowebprompt.engine.runner --config config.yaml --no-hold --max-runtime 3600
        """,
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--no-hold",
        action="store_true",
        help="Exit immediately after completion",
    )
    parser.add_argument(
        "--max-runtime",
        type=int,
        default=0,
        help="Maximum runtime in seconds (0 = unlimited)",
    )
    args = parser.parse_args()

    # Signal handlers
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        # Load .env
        env_path = Path(__file__).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)

        # Load config
        config_path = Path(args.config)
        if not config_path.is_absolute():
            # Try current directory first
            if (Path.cwd() / config_path).exists():
                config_path = Path.cwd() / config_path
            # Then try relative to script
            elif (Path(__file__).parent / config_path).exists():
                config_path = Path(__file__).parent / config_path

        if not config_path.exists():
            print(f"Config file not found: {config_path}")
            sys.exit(1)

        config = load_config(str(config_path))

        # Apply CLI overrides
        if args.max_runtime > 0:
            if "claude_web" not in config:
                config["claude_web"] = {}
            config["claude_web"]["max_sec_per_task"] = args.max_runtime

        # Setup logging
        task_name = config.get("task_name", "unknown_task")
        global logger
        logger, _ = setup_logging(config, __name__, task_name=task_name)

        # Run automation
        logger.info("=" * 60)
        logger.info("autowebprompt Engine Runner Starting")
        logger.info("=" * 60)
        logger.info(f"Config: {config_path}")
        logger.info(f"Task: {task_name}")

        success = asyncio.run(run_automation(config))

        if success:
            print("\nSUCCESS")
        else:
            print("\nFAILED")

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Script failed: {e}")
        import traceback

        logger.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
