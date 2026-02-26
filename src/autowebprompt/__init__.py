"""autowebprompt - Automate ChatGPT and Claude web UIs with Playwright."""

__version__ = "0.1.0"

from .agents.base import WebAgent, AgentState, ConversationMessage, TaskStatus, PipelineError

__all__ = [
    "WebAgent",
    "AgentState",
    "ConversationMessage",
    "TaskStatus",
    "PipelineError",
    "__version__",
]
