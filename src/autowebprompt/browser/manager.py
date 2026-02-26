"""
Browser management for autowebprompt.

Uses Chrome CDP mode by default to bypass Cloudflare detection.
Supports Chrome, Chrome Canary, and Chromium.
"""

import asyncio
import logging
import os
import platform
import socket
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Default CDP Configuration
DEFAULT_CDP_PORT = 9222
DEFAULT_PROFILE_DIR = os.path.expanduser("~/.autowebprompt-chrome-profile")

# Chrome paths (tries Canary first, then regular Chrome)
CHROME_PATHS = [
    # Chrome Canary (preferred)
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",  # macOS
    os.path.expanduser("~/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
    "/usr/bin/google-chrome-canary",  # Linux
    "/usr/bin/google-chrome-unstable",  # Linux alt
    # Windows Chrome Canary
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome SxS", "Application", "chrome.exe"),
    # Regular Chrome (fallback)
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
    os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    "/usr/bin/google-chrome",  # Linux
    "/usr/bin/google-chrome-stable",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",  # Windows
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
]


def find_chrome() -> str | None:
    """Find Chrome installation path."""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return None


def is_cdp_available(port: int = DEFAULT_CDP_PORT) -> bool:
    """Check if Chrome with debugging port is already running."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(("127.0.0.1", port))
    sock.close()
    return result == 0


def launch_chrome_cdp(
    headless: bool = False,
    port: int = DEFAULT_CDP_PORT,
    profile_dir: str = DEFAULT_PROFILE_DIR,
) -> subprocess.Popen | None:
    """Launch Chrome with remote debugging enabled."""
    chrome_path = find_chrome()

    if not chrome_path:
        logger.error("Chrome not found! Please install Chrome or Chrome Canary")
        return None

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]

    if headless:
        args.append("--headless=new")

    logger.info(f"Launching Chrome with CDP: {chrome_path}")
    logger.info(f"Profile: {profile_dir}")

    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return process


async def wait_for_chrome_ready(port: int = DEFAULT_CDP_PORT, timeout: int = 30) -> bool:
    """Wait for Chrome to be ready for CDP connection."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        if is_cdp_available(port):
            logger.info("Chrome is ready for CDP connection")
            return True
        await asyncio.sleep(0.5)

    logger.error(f"Chrome didn't start within {timeout} seconds")
    return False


class BrowserManager:
    """
    Manages browser instances for web agent automation.

    Uses Chrome CDP mode by default to bypass Cloudflare.
    """

    def __init__(self, config: dict):
        """
        Initialize browser manager.

        Args:
            config: Configuration dictionary with browser settings.
                    Looks for browser config under 'chatgpt_web.browser'
                    or 'claude_web.browser' keys.
        """
        self.config = config
        # Support both claude_web and chatgpt_web config keys
        browser_config = (
            config.get("chatgpt_web", {}).get("browser", {})
            or config.get("claude_web", {}).get("browser", {})
        )

        self.browser_type = browser_config.get("type", "chrome").lower()
        self.headless = browser_config.get("headless", False)
        self.timeout = browser_config.get("timeout", 30000)
        self.cdp_port = browser_config.get("cdp_port", DEFAULT_CDP_PORT)
        self.profile_dir = browser_config.get("profile_dir", DEFAULT_PROFILE_DIR)

    def is_cdp_mode(self) -> bool:
        """Check if using Chrome CDP mode."""
        return self.browser_type in ("chrome_canary", "cdp", "chrome")

    async def launch_browser(self, playwright):
        """
        Launch browser with automatic mode detection.

        Args:
            playwright: Playwright instance

        Returns:
            tuple: (browser, context) instances
        """
        if self.is_cdp_mode():
            return await self._launch_browser_cdp(playwright)
        else:
            return await self._launch_browser_classic(playwright)

    async def _launch_browser_cdp(self, playwright):
        """Connect to Chrome via CDP (Chrome DevTools Protocol)."""
        cdp_url = f"http://127.0.0.1:{self.cdp_port}"
        logger.info(f"Using Chrome CDP mode on port {self.cdp_port} (bypasses Cloudflare)")

        # Check if Chrome is already running with CDP
        if not is_cdp_available(self.cdp_port):
            if self.cdp_port != DEFAULT_CDP_PORT:
                raise RuntimeError(
                    f"Chrome not running on port {self.cdp_port}. "
                    f"Launch it with: chrome --remote-debugging-port={self.cdp_port}"
                )
            logger.info("Chrome not running with CDP, launching...")

            # Determine if we need headless mode
            display = os.environ.get("DISPLAY", "")
            use_headless = self.headless or (not display and platform.system() != "Darwin")

            process = launch_chrome_cdp(
                headless=use_headless,
                port=self.cdp_port,
                profile_dir=self.profile_dir,
            )
            if not process:
                raise RuntimeError("Chrome not found. Please install Chrome or Chrome Canary")

            if not await wait_for_chrome_ready(self.cdp_port):
                process.terminate()
                raise RuntimeError("Chrome failed to start with CDP")
        else:
            logger.info(f"Chrome already running on port {self.cdp_port}")

        # Connect via CDP
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            logger.info(f"Connected to Chrome via CDP ({cdp_url})")
        except Exception as e:
            logger.error(f"Failed to connect to Chrome: {e}")
            raise

        # Get existing context or create new one
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            logger.info(f"Using existing context ({len(context.pages)} page(s))")
        else:
            context = await browser.new_context(ignore_https_errors=True)
            logger.info("Created new browser context")

        context.set_default_timeout(self.timeout)
        return browser, context

    async def _launch_browser_classic(self, playwright):
        """Launch browser using classic Playwright mode."""
        logger.info(f"Using {self.browser_type} browser (classic mode)")

        if self.browser_type == "firefox":
            browser_instance = playwright.firefox
        elif self.browser_type == "webkit":
            browser_instance = playwright.webkit
        else:
            browser_instance = playwright.chromium

        # Get auth state path
        auth_state_path = self._get_auth_state_path()

        if auth_state_path.exists():
            logger.info(f"Loading auth state from: {auth_state_path}")
            import json
            with open(auth_state_path, "r") as f:
                storage_state = json.load(f)

            browser = await browser_instance.launch(headless=self.headless)
            context = await browser.new_context(
                storage_state=storage_state,
                ignore_https_errors=True
            )
        else:
            logger.warning(f"No auth state found at: {auth_state_path}")
            logger.warning("You may need to log in manually")

            browser = await browser_instance.launch(headless=self.headless)
            context = await browser.new_context(ignore_https_errors=True)

        context.set_default_timeout(self.timeout)
        return browser, context

    def _get_auth_state_path(self) -> Path:
        """Get path to auth state file."""
        return Path(self.profile_dir) / "auth_state.json"

    async def save_auth_state(self, context) -> bool:
        """Save browser auth state for future sessions."""
        try:
            auth_state_path = self._get_auth_state_path()
            auth_state_path.parent.mkdir(parents=True, exist_ok=True)
            storage_state = await context.storage_state()

            import json
            with open(auth_state_path, "w") as f:
                json.dump(storage_state, f, indent=2)

            logger.info(f"Saved auth state to: {auth_state_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save auth state: {e}")
            return False

    async def close_browser(self, context, browser=None):
        """Close browser resources."""
        if self.is_cdp_mode():
            logger.debug("CDP mode: keeping shared context alive")
            return

        if context:
            try:
                await context.close()
                logger.info("Browser context closed")
            except Exception as e:
                logger.warning(f"Error closing context: {e}")

        if browser:
            try:
                await browser.close()
            except Exception:
                pass
