"""Tests for autowebprompt.agents.base module."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from autowebprompt.agents.base import (
    AgentState,
    WebAgentState,
    TaskStatus,
    AGENT_STATUSES,
    PIPELINE_STATUSES,
    PipelineError,
    ConversationMessage,
    WebAgent,
)


class TestAgentState:
    """Tests for the AgentState enum."""

    def test_all_states_defined(self):
        """All expected states exist in the enum."""
        expected = {"RUNNING", "READY", "RATE_LIMITED", "AUTH_REQUIRED", "ERROR", "UNKNOWN"}
        actual = {s.name for s in AgentState}

        assert actual == expected

    def test_state_values_are_strings(self):
        """Each AgentState value is a descriptive string."""
        assert AgentState.RUNNING.value == "running"
        assert AgentState.READY.value == "ready"
        assert AgentState.RATE_LIMITED.value == "rate_limited"
        assert AgentState.AUTH_REQUIRED.value == "auth_required"
        assert AgentState.ERROR.value == "error"
        assert AgentState.UNKNOWN.value == "unknown"

    def test_backward_compat_alias(self):
        """WebAgentState is an alias for AgentState."""
        assert WebAgentState is AgentState


class TestTaskStatus:
    """Tests for the TaskStatus enum."""

    def test_is_str_enum(self):
        """TaskStatus members are also strings."""
        assert isinstance(TaskStatus.SUCCESS, str)
        assert TaskStatus.SUCCESS == "success"

    def test_agent_statuses_set(self):
        """AGENT_STATUSES contains exactly the agent-side statuses."""
        expected = {
            TaskStatus.SUCCESS,
            TaskStatus.TIMEOUT,
            TaskStatus.PROMPT_FAILED,
            TaskStatus.DOWNLOAD_FAILED,
            TaskStatus.FILE_CORRUPTED,
            TaskStatus.MISSING_SHEETS,
        }
        assert AGENT_STATUSES == expected

    def test_pipeline_statuses_set(self):
        """PIPELINE_STATUSES contains exactly the pipeline-side statuses."""
        expected = {
            TaskStatus.NAVIGATION_FAILED,
            TaskStatus.AUTH_FAILED,
            TaskStatus.UPLOAD_FAILED,
            TaskStatus.RATE_LIMITED,
            TaskStatus.UNKNOWN,
        }
        assert PIPELINE_STATUSES == expected

    def test_no_overlap_between_agent_and_pipeline(self):
        """Agent and pipeline status sets do not overlap."""
        assert AGENT_STATUSES.isdisjoint(PIPELINE_STATUSES)

    def test_all_members_in_one_set(self):
        """Every TaskStatus member belongs to either AGENT_STATUSES or PIPELINE_STATUSES."""
        all_statuses = {s for s in TaskStatus}
        categorized = AGENT_STATUSES | PIPELINE_STATUSES

        assert all_statuses == categorized

    def test_string_comparison(self):
        """TaskStatus members can be compared directly with plain strings."""
        assert TaskStatus.SUCCESS == "success"
        assert TaskStatus.TIMEOUT == "timeout"
        assert TaskStatus.RATE_LIMITED == "rate_limited"

    def test_string_in_format(self):
        """TaskStatus members work in f-strings and format()."""
        msg = f"Status: {TaskStatus.SUCCESS.value}"
        assert msg == "Status: success"


class TestPipelineError:
    """Tests for the PipelineError exception."""

    def test_stores_status(self):
        """PipelineError.status holds the TaskStatus value."""
        err = PipelineError(TaskStatus.AUTH_FAILED, "Login expired")

        assert err.status == TaskStatus.AUTH_FAILED

    def test_message_from_args(self):
        """PipelineError uses the provided message as str()."""
        err = PipelineError(TaskStatus.NAVIGATION_FAILED, "Page not found")

        assert str(err) == "Page not found"

    def test_default_message_is_status_value(self):
        """When no message is provided, str(err) falls back to the status value."""
        err = PipelineError(TaskStatus.UPLOAD_FAILED)

        assert str(err) == "upload_failed"

    def test_is_exception(self):
        """PipelineError is a subclass of Exception."""
        assert issubclass(PipelineError, Exception)

    def test_can_be_raised_and_caught(self):
        """PipelineError can be raised and caught with status inspection."""
        with pytest.raises(PipelineError) as exc_info:
            raise PipelineError(TaskStatus.RATE_LIMITED, "Slow down")

        assert exc_info.value.status == TaskStatus.RATE_LIMITED
        assert "Slow down" in str(exc_info.value)


class TestConversationMessage:
    """Tests for the ConversationMessage dataclass."""

    def test_required_fields(self):
        """ConversationMessage requires role and content."""
        msg = ConversationMessage(role="user", content="Hello")

        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_optional_timestamp_defaults_to_none(self):
        """timestamp defaults to None when not provided."""
        msg = ConversationMessage(role="assistant", content="Hi there")

        assert msg.timestamp is None

    def test_optional_metadata_defaults_to_empty_dict(self):
        """metadata defaults to an empty dict when not provided."""
        msg = ConversationMessage(role="user", content="test")

        assert msg.metadata == {}

    def test_metadata_default_not_shared(self):
        """Each instance gets its own metadata dict (no shared mutable default)."""
        msg1 = ConversationMessage(role="user", content="a")
        msg2 = ConversationMessage(role="user", content="b")

        msg1.metadata["key"] = "value"

        assert "key" not in msg2.metadata

    def test_with_all_fields(self):
        """ConversationMessage with all fields populated."""
        ts = datetime(2026, 2, 26, 12, 0, 0)
        meta = {"tokens": 150, "model": "opus-4.5"}
        msg = ConversationMessage(
            role="assistant",
            content="Analysis complete.",
            timestamp=ts,
            metadata=meta,
        )

        assert msg.role == "assistant"
        assert msg.content == "Analysis complete."
        assert msg.timestamp == ts
        assert msg.metadata == meta

    def test_equality(self):
        """Two ConversationMessages with same fields are equal (dataclass behavior)."""
        ts = datetime(2026, 1, 1)
        msg1 = ConversationMessage(role="user", content="hi", timestamp=ts, metadata={})
        msg2 = ConversationMessage(role="user", content="hi", timestamp=ts, metadata={})

        assert msg1 == msg2


class TestWebAgent:
    """Tests for the WebAgent abstract base class."""

    def test_cannot_instantiate_directly(self):
        """WebAgent cannot be instantiated because it has abstract methods."""
        with pytest.raises(TypeError, match="abstract method"):
            WebAgent(page=MagicMock(), config={})

    def test_subclass_must_implement_all_abstract_methods(self):
        """A subclass missing any abstract method cannot be instantiated."""

        class PartialAgent(WebAgent):
            async def navigate_to_new_chat(self):
                return True

            # Missing all other abstract methods

        with pytest.raises(TypeError):
            PartialAgent(page=MagicMock(), config={})

    def test_concrete_subclass_can_be_instantiated(self):
        """A fully concrete subclass can be instantiated."""

        class ConcreteAgent(WebAgent):
            async def navigate_to_new_chat(self):
                return True

            async def get_state(self):
                return AgentState.READY

            async def upload_files(self, file_paths):
                return True

            async def submit_prompt(self, prompt, prompt_number=1):
                return True

            async def wait_for_response(self, prompt_number=1):
                return "response"

            async def download_all_artifacts(self, download_dir=None, timeout=30000):
                return []

            async def get_conversation_history(self):
                return []

            async def process_all_prompts(self, files_to_upload=None):
                return True

            async def ensure_features_enabled(self):
                return True

        mock_page = MagicMock()
        agent = ConcreteAgent(page=mock_page, config={"key": "value"})

        assert agent.page is mock_page
        assert agent.config == {"key": "value"}
        assert agent.messages == []
        assert agent.current_response_count == 0

    def test_init_stores_optional_params(self):
        """WebAgent.__init__ stores shutdown_event and completion_logger."""

        class ConcreteAgent(WebAgent):
            async def navigate_to_new_chat(self):
                return True

            async def get_state(self):
                return AgentState.READY

            async def upload_files(self, file_paths):
                return True

            async def submit_prompt(self, prompt, prompt_number=1):
                return True

            async def wait_for_response(self, prompt_number=1):
                return "response"

            async def download_all_artifacts(self, download_dir=None, timeout=30000):
                return []

            async def get_conversation_history(self):
                return []

            async def process_all_prompts(self, files_to_upload=None):
                return True

            async def ensure_features_enabled(self):
                return True

        mock_event = MagicMock()
        mock_logger = MagicMock()
        agent = ConcreteAgent(
            page=MagicMock(),
            config={},
            shutdown_event=mock_event,
            completion_logger=mock_logger,
        )

        assert agent.shutdown_event is mock_event
        assert agent.completion_logger is mock_logger
