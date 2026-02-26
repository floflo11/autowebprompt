"""
WebAgent Abstract Base Class — Strategy Pattern for web-based AI agents.

Defines the common interface that all web-based AI agents (e.g., ClaudeWebAgent,
ChatGPTWebAgent) must implement. The engine and batch runner operate against this
base class, allowing new agents to be added without modifying orchestration logic.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Possible states for a web-based AI agent interface."""
    RUNNING = "running"
    READY = "ready"
    RATE_LIMITED = "rate_limited"
    AUTH_REQUIRED = "auth_required"
    ERROR = "error"
    UNKNOWN = "unknown"


# Backward compat alias
WebAgentState = AgentState


class TaskStatus(str, Enum):
    """Status of a task attempt — classifies both agent and pipeline outcomes."""

    # Agent statuses (agent was invoked, count toward agent_attempts)
    SUCCESS = "success"
    TIMEOUT = "timeout"
    PROMPT_FAILED = "prompt_failed"
    DOWNLOAD_FAILED = "download_failed"
    FILE_CORRUPTED = "file_corrupted"
    MISSING_SHEETS = "missing_sheets"

    # Pipeline statuses (pre-agent infra failures, DON'T count)
    NAVIGATION_FAILED = "navigation_failed"
    AUTH_FAILED = "auth_failed"
    UPLOAD_FAILED = "upload_failed"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


AGENT_STATUSES = {
    TaskStatus.SUCCESS,
    TaskStatus.TIMEOUT,
    TaskStatus.PROMPT_FAILED,
    TaskStatus.DOWNLOAD_FAILED,
    TaskStatus.FILE_CORRUPTED,
    TaskStatus.MISSING_SHEETS,
}

PIPELINE_STATUSES = {
    TaskStatus.NAVIGATION_FAILED,
    TaskStatus.AUTH_FAILED,
    TaskStatus.UPLOAD_FAILED,
    TaskStatus.RATE_LIMITED,
    TaskStatus.UNKNOWN,
}


class PipelineError(Exception):
    """Raised for pre-agent infrastructure failures (browser, nav, auth, file upload)."""

    def __init__(self, status: TaskStatus, message: str = ""):
        self.status = status
        super().__init__(message or status.value)


@dataclass
class ConversationMessage:
    """A single message in the conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


class WebAgent(ABC):
    """
    Abstract base class for web-based AI agent automation.

    Concrete subclasses (e.g., ClaudeWebAgent, ChatGPTWebAgent) implement
    the abstract methods with provider-specific Playwright selectors and
    interaction logic.

    Args:
        page: Playwright page instance connected to the browser.
        config: Configuration dictionary for the task and agent.
        shutdown_event: Optional asyncio.Event for graceful shutdown signaling.
        completion_logger: Optional logger for timing and completion tracking.
    """

    def __init__(
        self,
        page,
        config: dict,
        shutdown_event=None,
        completion_logger=None,
    ):
        self.page = page
        self.config = config
        self.shutdown_event = shutdown_event
        self.completion_logger = completion_logger

        # Conversation state
        self.messages: list[ConversationMessage] = []
        self.current_response_count = 0

    @abstractmethod
    async def navigate_to_new_chat(self) -> bool:
        """Navigate to the provider's chat interface to start a fresh conversation."""
        ...

    @abstractmethod
    async def get_state(self) -> AgentState:
        """Determine the current state of the web interface."""
        ...

    @abstractmethod
    async def upload_files(self, file_paths: list[str]) -> bool:
        """Upload files to the current conversation."""
        ...

    @abstractmethod
    async def submit_prompt(self, prompt: str, prompt_number: int = 1) -> bool:
        """Submit a prompt to the AI agent."""
        ...

    @abstractmethod
    async def wait_for_response(self, prompt_number: int = 1) -> Optional[str]:
        """Wait for the AI agent to finish responding and extract the response."""
        ...

    @abstractmethod
    async def download_all_artifacts(
        self, download_dir: Optional[str] = None, timeout: int = 30000
    ) -> list[str]:
        """Download all artifacts produced by the AI agent's response."""
        ...

    @abstractmethod
    async def get_conversation_history(self) -> list[dict]:
        """Get the full conversation history."""
        ...

    @abstractmethod
    async def process_all_prompts(self, files_to_upload: list = None) -> bool:
        """Process all prompts from config sequentially."""
        ...

    @abstractmethod
    async def ensure_features_enabled(self) -> bool:
        """Ensure all provider-specific features are enabled."""
        ...
