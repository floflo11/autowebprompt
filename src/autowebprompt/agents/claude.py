"""
Claude Web Agent — Automate interactions with Claude.ai web interface.

Handles navigation, extended thinking, web search, file upload,
prompt submission, response extraction, and artifact download.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from autowebprompt.agents.base import WebAgent, AgentState, ConversationMessage

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of running a task through Claude.ai."""
    task_name: str
    success: bool
    messages: list
    start_time: datetime
    end_time: datetime
    error_msg: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        return (self.end_time - self.start_time).total_seconds()


class ClaudeWebAgent(WebAgent):
    """Agent for automating Claude.ai web interface."""

    CLAUDE_BASE_URL = "https://claude.ai"
    CLAUDE_NEW_CHAT_URL = "https://claude.ai/new"

    SELECTORS = {
        "chat_input": 'div[contenteditable="true"][data-placeholder]',
        "chat_input_alt": 'div[enterkeyhint="enter"]',
        "chat_textarea": 'fieldset div[contenteditable="true"]',
        "send_button": 'button[aria-label="Send message"]',
        "send_button_alt": 'button:has(svg[viewBox="0 0 32 32"])',
        "stop_button": 'button[aria-label="Stop response"]',
        "stop_button_alt": 'button:has-text("Stop")',
        "response_content": '[class*="prose"]',
        "attach_button": 'button[aria-label="Attach files"]',
        "file_input": 'input[type="file"]',
        "assistant_message": 'div[data-is-streaming]',
        "message_container": 'div[class*="message"]',
        "login_button": 'a:has-text("Log in")',
        "email_input": 'input[type="email"]',
        "rate_limit_message": 'text="You\'ve reached"',
        "model_selector": 'button[data-testid="model-selector"]',
        "extended_thinking_button": 'button[aria-label="Extended thinking"]',
        "toggle_menu_button": 'button[aria-label="Toggle menu"]',
        "web_search_checkbox": 'div[role="menuitemcheckbox"]:has-text("Web search")',
        "download_button": 'button:has-text("Download")',
        "download_button_aria": '[aria-label="Download"]',
        "download_button_text": 'button:text("Download")',
        "download_button_link": 'a:has-text("Download")',
    }

    def __init__(self, page, config: dict, shutdown_event=None, completion_logger=None):
        super().__init__(page, config, shutdown_event, completion_logger)
        self.agent_config = config.get("claude_web", {})
        self.max_wait_per_prompt = self.agent_config.get("max_wait_per_prompt_seconds", 1800)
        self.check_interval = self.agent_config.get("check_interval_seconds", 2)

    async def navigate_to_new_chat(self) -> bool:
        try:
            project_url = self.agent_config.get("project_url")
            project_id = self.agent_config.get("project_id")

            if project_url:
                if "/project/" in project_url:
                    project_id = project_url.split("/project/")[1].split("/")[0].split("?")[0]

            if project_id:
                nav_url = f"{self.CLAUDE_BASE_URL}/project/{project_id}"
                logger.info(f"Navigating to project: {nav_url}...")
            else:
                nav_url = self.CLAUDE_NEW_CHAT_URL
                logger.info(f"Navigating to {nav_url}...")

            await self.page.goto(nav_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)

            state = await self.get_state()
            if state == AgentState.AUTH_REQUIRED:
                logger.warning("Authentication required - please log in manually")
                return False

            logger.info(f"Successfully navigated to Claude.ai (state: {state.value})")

            if self.agent_config.get("enable_extended_thinking", True):
                await self.ensure_extended_thinking_enabled()
            if self.agent_config.get("enable_web_search", True):
                await self.ensure_web_search_enabled()

            return True
        except Exception as e:
            logger.error(f"Failed to navigate to Claude.ai: {e}")
            return False

    async def ensure_extended_thinking_enabled(self) -> bool:
        try:
            logger.info("Checking Extended Thinking status...")
            try:
                btn = self.page.get_by_role("button", name="Extended thinking")
                if await btn.is_visible(timeout=3000):
                    is_pressed = await btn.get_attribute("aria-pressed")
                    if is_pressed == "true":
                        logger.info("Extended Thinking is already enabled")
                        return True
                    await btn.click()
                    await asyncio.sleep(0.5)
                    is_pressed = await btn.get_attribute("aria-pressed")
                    if is_pressed == "true":
                        logger.info("Extended Thinking enabled successfully")
                        return True
                    else:
                        logger.warning("Failed to enable Extended Thinking")
                        return False
            except Exception as e:
                logger.debug(f"Role-based selector failed: {e}")

            btn = await self.page.query_selector(self.SELECTORS["extended_thinking_button"])
            if btn and await btn.is_visible():
                is_pressed = await btn.get_attribute("aria-pressed")
                if is_pressed == "true":
                    logger.info("Extended Thinking is already enabled")
                    return True
                await btn.click()
                await asyncio.sleep(0.5)
                logger.info("Extended Thinking enabled successfully")
                return True

            logger.warning("Extended Thinking button not found")
            return False
        except Exception as e:
            logger.error(f"Error enabling Extended Thinking: {e}")
            return False

    async def ensure_web_search_enabled(self) -> bool:
        try:
            logger.info("Checking Web Search status...")
            try:
                menu_btn = self.page.get_by_role("button", name="Toggle menu")
                if await menu_btn.is_visible(timeout=3000):
                    await menu_btn.click()
                    await asyncio.sleep(0.5)
                else:
                    logger.warning("Toggle menu button not visible")
                    return False
            except Exception as e:
                logger.debug(f"Role-based menu selector failed: {e}")
                menu_btn = await self.page.query_selector(self.SELECTORS["toggle_menu_button"])
                if menu_btn and await menu_btn.is_visible():
                    await menu_btn.click()
                    await asyncio.sleep(0.5)
                else:
                    logger.warning("Toggle menu button not found")
                    return False

            try:
                web_search = self.page.get_by_role("menuitemcheckbox", name="Web search")
                if await web_search.is_visible(timeout=2000):
                    is_checked = await web_search.get_attribute("aria-checked")
                    if is_checked == "true":
                        logger.info("Web Search is already enabled")
                        await self.page.keyboard.press("Escape")
                        return True
                    await web_search.click()
                    await asyncio.sleep(0.3)
                    logger.info("Web Search enabled successfully")
                    return True
            except Exception as e:
                logger.debug(f"Role-based Web Search selector failed: {e}")

            web_search = await self.page.query_selector(self.SELECTORS["web_search_checkbox"])
            if web_search and await web_search.is_visible():
                is_checked = await web_search.get_attribute("aria-checked")
                if is_checked == "true":
                    logger.info("Web Search is already enabled")
                    await self.page.keyboard.press("Escape")
                    return True
                await web_search.click()
                await asyncio.sleep(0.3)
                logger.info("Web Search enabled successfully")
                return True

            logger.warning("Web Search checkbox not found")
            await self.page.keyboard.press("Escape")
            return False
        except Exception as e:
            logger.error(f"Error enabling Web Search: {e}")
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    async def ensure_features_enabled(self) -> bool:
        et_ok = await self.ensure_extended_thinking_enabled()
        ws_ok = await self.ensure_web_search_enabled()
        return et_ok and ws_ok

    async def get_state(self) -> AgentState:
        try:
            rate_limit = await self.page.query_selector(self.SELECTORS["rate_limit_message"])
            if rate_limit:
                return AgentState.RATE_LIMITED

            login_btn = await self.page.query_selector(self.SELECTORS["login_button"])
            if login_btn and await login_btn.is_visible():
                return AgentState.AUTH_REQUIRED

            for selector in [self.SELECTORS["stop_button"], self.SELECTORS["stop_button_alt"]]:
                try:
                    stop_btn = await self.page.query_selector(selector)
                    if stop_btn and await stop_btn.is_visible():
                        return AgentState.RUNNING
                except Exception:
                    continue

            for selector in [
                self.SELECTORS["chat_input"],
                self.SELECTORS["chat_input_alt"],
                self.SELECTORS["chat_textarea"],
            ]:
                try:
                    input_field = await self.page.query_selector(selector)
                    if input_field and await input_field.is_visible():
                        return AgentState.READY
                except Exception:
                    continue

            return AgentState.UNKNOWN
        except Exception as e:
            logger.debug(f"Error getting state: {e}")
            return AgentState.UNKNOWN

    async def _find_input_field(self):
        for selector in [
            self.SELECTORS["chat_input"],
            self.SELECTORS["chat_input_alt"],
            self.SELECTORS["chat_textarea"],
        ]:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except Exception:
                continue
        return None

    async def _find_send_button(self):
        for selector in [self.SELECTORS["send_button"], self.SELECTORS["send_button_alt"]]:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    return btn
            except Exception:
                continue
        return None

    async def upload_files(self, file_paths: list[str]) -> bool:
        if not file_paths:
            return True
        try:
            logger.info(f"Uploading {len(file_paths)} file(s)...")
            file_input = await self.page.query_selector(self.SELECTORS["file_input"])
            if file_input:
                await file_input.set_input_files(file_paths)
            else:
                attach_btn = await self.page.query_selector(self.SELECTORS["attach_button"])
                if not attach_btn:
                    logger.error("Could not find file upload mechanism")
                    return False
                async with self.page.expect_file_chooser() as fc:
                    await attach_btn.click()
                chooser = await fc.value
                await chooser.set_files(file_paths)

            await asyncio.sleep(2 + len(file_paths))
            logger.info(f"Uploaded {len(file_paths)} file(s)")
            return True
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            return False

    async def submit_prompt(self, prompt: str, prompt_number: int = 1) -> bool:
        try:
            logger.info(f"Submitting prompt #{prompt_number}: {prompt[:100]}...")
            input_field = await self._find_input_field()
            if not input_field:
                logger.error("Could not find chat input field")
                return False

            await input_field.click()
            await asyncio.sleep(0.3)
            await input_field.fill("")
            await asyncio.sleep(0.1)

            try:
                await input_field.fill(prompt)
            except Exception:
                await self.page.keyboard.type(prompt, delay=10)

            await asyncio.sleep(0.5)

            send_btn = await self._find_send_button()
            if send_btn:
                await send_btn.click()
                logger.info("Clicked send button")
            else:
                await self.page.keyboard.press("Enter")
                logger.info("Pressed Enter to send")

            self.messages.append(ConversationMessage(role="user", content=prompt))
            return True
        except Exception as e:
            logger.error(f"Failed to submit prompt: {e}")
            return False

    async def wait_for_response(self, prompt_number: int = 1) -> Optional[str]:
        logger.info(f"Waiting for response to prompt #{prompt_number}...")
        elapsed = 0
        saw_running = False

        while elapsed < self.max_wait_per_prompt:
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.warning("Shutdown signal received")
                return None

            await asyncio.sleep(self.check_interval)
            elapsed += self.check_interval
            state = await self.get_state()

            if state == AgentState.RUNNING:
                saw_running = True
                if elapsed % 10 == 0:
                    logger.info(f"   [{elapsed}s] Claude is generating...")
                continue

            if state == AgentState.RATE_LIMITED:
                logger.error("Rate limit reached!")
                return None

            if state == AgentState.READY:
                if not saw_running:
                    try:
                        responses = await self.page.query_selector_all(self.SELECTORS["response_content"])
                        if len(responses) > 1:
                            saw_running = True
                            logger.info(f"   [{elapsed}s] Detected response content (fallback)")
                        elif elapsed % 10 == 0:
                            logger.info(f"   [{elapsed}s] Waiting for Claude to start...")
                            continue
                    except Exception:
                        if elapsed % 10 == 0:
                            logger.info(f"   [{elapsed}s] Waiting for Claude to start...")
                        continue
                    if not saw_running:
                        continue

                await asyncio.sleep(1)
                final_state = await self.get_state()
                if final_state == AgentState.READY:
                    logger.info(f"Prompt #{prompt_number} completed after {elapsed}s")
                    response = await self._extract_last_response()
                    if response:
                        self.messages.append(ConversationMessage(role="assistant", content=response))
                    return response

        logger.error(f"Timeout waiting for response to prompt #{prompt_number}")
        return None

    async def _extract_last_response(self) -> Optional[str]:
        try:
            selectors = [
                'div[data-is-streaming="false"]',
                'div.font-claude-message',
                'div[class*="prose"]',
                'article div',
            ]
            for selector in selectors:
                try:
                    elements = await self.page.query_selector_all(selector)
                    if elements:
                        last_el = elements[-1]
                        text = await last_el.text_content()
                        if text and len(text.strip()) > 0:
                            return text.strip()
                except Exception:
                    continue

            try:
                conversation = await self.page.query_selector('main')
                if conversation:
                    text = await conversation.text_content()
                    return text.strip() if text else None
            except Exception:
                pass
            return None
        except Exception as e:
            logger.debug(f"Error extracting response: {e}")
            return None

    async def process_all_prompts(self, files_to_upload: list = None) -> bool:
        prompts = self.config.get("prompts", [])
        if not prompts:
            logger.error("No prompts found in config")
            return False
        if isinstance(prompts, str):
            prompts = [prompts]

        if files_to_upload:
            logger.info(f"Uploading {len(files_to_upload)} file(s) before prompts...")
            if not await self.upload_files(files_to_upload):
                logger.error("File upload failed")
                return False
            await asyncio.sleep(2)

        logger.info(f"Processing {len(prompts)} prompt(s)...")

        for i, prompt in enumerate(prompts, 1):
            if self.shutdown_event and self.shutdown_event.is_set():
                logger.warning(f"Shutdown signal before prompt #{i}")
                return False

            logger.info(f"\n{'='*60}")
            logger.info(f"PROMPT {i}/{len(prompts)}")
            logger.info(f"{'='*60}")

            if self.completion_logger:
                self.completion_logger.start_prompt(prompt)

            if not await self.submit_prompt(prompt, i):
                logger.error(f"Failed to submit prompt #{i}")
                if self.completion_logger:
                    self.completion_logger.end_prompt(success=False)
                return False

            response = await self.wait_for_response(i)
            if response is None:
                logger.error(f"Failed to get response for prompt #{i}")
                if self.completion_logger:
                    self.completion_logger.end_prompt(success=False)
                return False

            logger.info(f"Prompt #{i} completed successfully")
            logger.info(f"Response preview: {response[:200]}...")

            if self.completion_logger:
                self.completion_logger.end_prompt(success=True, response_length=len(response))
            await asyncio.sleep(2)

        logger.info(f"\nAll {len(prompts)} prompts completed!")
        return True

    async def get_conversation_history(self) -> list[dict]:
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat() if msg.timestamp else None,
            }
            for msg in self.messages
        ]

    async def download_all_artifacts(self, download_dir: Optional[str] = None, timeout: int = 30000) -> list[str]:
        downloaded_files = []
        try:
            logger.info("Looking for artifacts to download...")
            await asyncio.sleep(1)

            try:
                download_all_btn = self.page.get_by_role("button", name="Download all")
                if await download_all_btn.is_visible(timeout=2000):
                    logger.info("Found 'Download all' button, clicking...")
                    async with self.page.expect_download(timeout=timeout) as download_info:
                        await download_all_btn.click()
                    download = await download_info.value
                    if download_dir:
                        save_path = Path(download_dir) / download.suggested_filename
                        await download.save_as(str(save_path))
                    else:
                        save_path = Path(download.path())
                    downloaded_files.append(str(save_path))
                    logger.info(f"Downloaded all artifacts to: {save_path}")
                    return downloaded_files
            except Exception:
                pass

            logger.info("Looking for individual artifact download buttons...")
            download_selectors = [
                self.SELECTORS["download_button"],
                self.SELECTORS["download_button_aria"],
            ]
            all_download_btns = []
            for selector in download_selectors:
                try:
                    btns = await self.page.query_selector_all(selector)
                    if btns:
                        all_download_btns.extend(btns)
                        break
                except Exception:
                    continue

            if not all_download_btns:
                logger.warning("No download buttons found on page")
            else:
                logger.info(f"Found {len(all_download_btns)} download button(s)")
                for i, btn in enumerate(all_download_btns):
                    try:
                        if not await btn.is_visible():
                            continue
                        logger.info(f"Downloading artifact {i+1}/{len(all_download_btns)}...")
                        async with self.page.expect_download(timeout=timeout) as download_info:
                            await btn.click()
                        download = await download_info.value
                        if download_dir:
                            save_path = Path(download_dir) / download.suggested_filename
                            await download.save_as(str(save_path))
                        else:
                            save_path = Path(download.path())
                        downloaded_files.append(str(save_path))
                        logger.info(f"Downloaded: {save_path}")
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"Failed to download artifact {i+1}: {e}")
                        continue
        except Exception as e:
            logger.error(f"Failed to download artifacts: {e}")

        return downloaded_files
