"""Tests for autowebprompt.browser.manager module."""

import socket
from unittest.mock import patch, MagicMock

import pytest

from autowebprompt.browser.manager import (
    find_chrome,
    is_cdp_available,
    launch_chrome_cdp,
    BrowserManager,
    DEFAULT_CDP_PORT,
    DEFAULT_PROFILE_DIR,
    CHROME_PATHS,
)


class TestFindChrome:
    """Tests for find_chrome()."""

    def test_returns_first_existing_path(self):
        """find_chrome returns the first path that exists on disk."""
        # Mock os.path.exists to return True only for a specific path
        fake_path = CHROME_PATHS[0]

        def mock_exists(path):
            return path == fake_path

        with patch("os.path.exists", side_effect=mock_exists):
            result = find_chrome()

        assert result == fake_path

    def test_returns_none_when_no_chrome_found(self):
        """find_chrome returns None when no Chrome binary exists."""
        with patch("os.path.exists", return_value=False):
            result = find_chrome()

        assert result is None

    def test_prefers_canary_over_regular(self):
        """Chrome Canary paths come before regular Chrome in the search order."""
        # The first entry in CHROME_PATHS should be Chrome Canary (macOS)
        assert "Canary" in CHROME_PATHS[0]

    def test_returns_second_match_if_first_missing(self):
        """If the first candidate does not exist, the second is tried."""
        def mock_exists(path):
            return path == CHROME_PATHS[1]

        with patch("os.path.exists", side_effect=mock_exists):
            result = find_chrome()

        assert result == CHROME_PATHS[1]


class TestIsCdpAvailable:
    """Tests for is_cdp_available()."""

    def test_returns_true_when_port_open(self):
        """is_cdp_available returns True when a connection succeeds (connect_ex == 0)."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.connect_ex.return_value = 0

        with patch("socket.socket", return_value=mock_sock):
            result = is_cdp_available(9222)

        assert result is True
        mock_sock.connect_ex.assert_called_once_with(("127.0.0.1", 9222))
        mock_sock.close.assert_called_once()

    def test_returns_false_when_port_closed(self):
        """is_cdp_available returns False when a connection fails (connect_ex != 0)."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.connect_ex.return_value = 111  # Connection refused

        with patch("socket.socket", return_value=mock_sock):
            result = is_cdp_available(9222)

        assert result is False

    def test_uses_custom_port(self):
        """is_cdp_available connects to the specified custom port."""
        mock_sock = MagicMock(spec=socket.socket)
        mock_sock.connect_ex.return_value = 0

        with patch("socket.socket", return_value=mock_sock):
            is_cdp_available(9333)

        mock_sock.connect_ex.assert_called_once_with(("127.0.0.1", 9333))

    def test_default_port_is_9222(self):
        """The default port should be 9222."""
        assert DEFAULT_CDP_PORT == 9222


class TestLaunchChromeCdp:
    """Tests for launch_chrome_cdp()."""

    def test_returns_none_when_chrome_not_found(self):
        """launch_chrome_cdp returns None when no Chrome binary is found."""
        with patch("autowebprompt.browser.manager.find_chrome", return_value=None):
            result = launch_chrome_cdp()

        assert result is None

    def test_launches_subprocess_with_correct_args(self):
        """launch_chrome_cdp calls subprocess.Popen with the right arguments."""
        fake_chrome = "/usr/bin/fake-chrome"

        with (
            patch("autowebprompt.browser.manager.find_chrome", return_value=fake_chrome),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            result = launch_chrome_cdp(port=9333, profile_dir="/tmp/profile")

        assert result is not None
        args = mock_popen.call_args[0][0]
        assert args[0] == fake_chrome
        assert "--remote-debugging-port=9333" in args
        assert "--user-data-dir=/tmp/profile" in args

    def test_headless_flag_appended(self):
        """When headless=True, --headless=new is appended to args."""
        fake_chrome = "/usr/bin/fake-chrome"

        with (
            patch("autowebprompt.browser.manager.find_chrome", return_value=fake_chrome),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            launch_chrome_cdp(headless=True)

        args = mock_popen.call_args[0][0]
        assert "--headless=new" in args

    def test_headless_flag_not_appended_by_default(self):
        """When headless=False (default), --headless=new is NOT in args."""
        fake_chrome = "/usr/bin/fake-chrome"

        with (
            patch("autowebprompt.browser.manager.find_chrome", return_value=fake_chrome),
            patch("subprocess.Popen") as mock_popen,
        ):
            mock_popen.return_value = MagicMock()
            launch_chrome_cdp(headless=False)

        args = mock_popen.call_args[0][0]
        assert "--headless=new" not in args


class TestBrowserManager:
    """Tests for BrowserManager class."""

    def test_init_defaults(self):
        """BrowserManager with empty config uses sensible defaults."""
        mgr = BrowserManager({})

        assert mgr.browser_type == "chrome"
        assert mgr.headless is False
        assert mgr.timeout == 30000
        assert mgr.cdp_port == DEFAULT_CDP_PORT
        assert mgr.profile_dir == DEFAULT_PROFILE_DIR

    def test_init_from_claude_web_config(self):
        """BrowserManager reads settings from claude_web.browser section."""
        config = {
            "claude_web": {
                "browser": {
                    "type": "chrome_canary",
                    "headless": True,
                    "timeout": 60000,
                    "cdp_port": 9333,
                    "profile_dir": "/custom/profile",
                }
            }
        }

        mgr = BrowserManager(config)

        assert mgr.browser_type == "chrome_canary"
        assert mgr.headless is True
        assert mgr.timeout == 60000
        assert mgr.cdp_port == 9333
        assert mgr.profile_dir == "/custom/profile"

    def test_init_from_chatgpt_web_config(self):
        """BrowserManager reads settings from chatgpt_web.browser section."""
        config = {
            "chatgpt_web": {
                "browser": {
                    "type": "cdp",
                    "headless": False,
                }
            }
        }

        mgr = BrowserManager(config)

        assert mgr.browser_type == "cdp"
        assert mgr.headless is False

    def test_is_cdp_mode_chrome_canary(self):
        """is_cdp_mode returns True for chrome_canary."""
        config = {"claude_web": {"browser": {"type": "chrome_canary"}}}
        mgr = BrowserManager(config)

        assert mgr.is_cdp_mode() is True

    def test_is_cdp_mode_chrome(self):
        """is_cdp_mode returns True for plain 'chrome'."""
        mgr = BrowserManager({})  # defaults to chrome
        assert mgr.is_cdp_mode() is True

    def test_is_cdp_mode_cdp(self):
        """is_cdp_mode returns True for 'cdp' type."""
        config = {"claude_web": {"browser": {"type": "cdp"}}}
        mgr = BrowserManager(config)

        assert mgr.is_cdp_mode() is True

    def test_is_not_cdp_mode_firefox(self):
        """is_cdp_mode returns False for firefox."""
        config = {"claude_web": {"browser": {"type": "firefox"}}}
        mgr = BrowserManager(config)

        assert mgr.is_cdp_mode() is False

    def test_is_not_cdp_mode_webkit(self):
        """is_cdp_mode returns False for webkit."""
        config = {"claude_web": {"browser": {"type": "webkit"}}}
        mgr = BrowserManager(config)

        assert mgr.is_cdp_mode() is False

    def test_get_auth_state_path(self):
        """_get_auth_state_path returns profile_dir / auth_state.json."""
        config = {"claude_web": {"browser": {"profile_dir": "/my/profile"}}}
        mgr = BrowserManager(config)

        path = mgr._get_auth_state_path()

        assert str(path) == "/my/profile/auth_state.json"

    def test_browser_type_is_lowercased(self):
        """Browser type string is lowercased during init."""
        config = {"claude_web": {"browser": {"type": "Chrome_Canary"}}}
        mgr = BrowserManager(config)

        assert mgr.browser_type == "chrome_canary"
