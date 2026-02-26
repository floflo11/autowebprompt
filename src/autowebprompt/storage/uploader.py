"""
Result Uploader — upload artifacts and conversation to S3 and database.

All cloud features are optional. If AWS credentials or DATABASE_URL are not set,
those features gracefully skip with a warning.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ResultUploader:
    """Handles uploading automation results to S3 and database."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.s3_bucket = self.config.get(
            "s3_bucket", os.environ.get("AWS_S3_BUCKET", "")
        )
        self.s3_prefix = self.config.get("s3_prefix", "")
        self.db_enabled = self.config.get("db_enabled", False)

        self.agent_model_name = self.config.get("agent_model_name", "")
        self.agent_model_type = self.config.get("agent_model_type", "gui")
        self.s3_artifact_prefix = self.config.get("s3_artifact_prefix", "attempts")
        self.s3_conversation_prefix = self.config.get("s3_conversation_prefix", "conversations")

        self._s3_client = None

    @property
    def s3_client(self):
        if self._s3_client is None:
            try:
                import boto3
                self._s3_client = boto3.client("s3")
            except ImportError:
                logger.warning("boto3 not installed — S3 uploads disabled. Install with: pip install autowebprompt[storage]")
                return None
        return self._s3_client

    def _get_timestamp_prefix(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def upload_file_to_s3(self, local_path: Path, s3_key: str) -> Optional[str]:
        if not self.s3_bucket:
            logger.warning("No S3 bucket configured — skipping upload")
            return None

        client = self.s3_client
        if client is None:
            return None

        try:
            local_path = Path(local_path)
            if not local_path.exists():
                logger.error(f"File not found: {local_path}")
                return None

            if self.s3_prefix:
                s3_key = f"{self.s3_prefix}/{s3_key}"

            client.upload_file(str(local_path), self.s3_bucket, s3_key)
            s3_uri = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"Uploaded to S3: {s3_uri}")
            return s3_uri
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            return None

    def upload_artifact(self, local_path: Path, task_name: str, task_source: str = "") -> Optional[str]:
        local_path = Path(local_path)
        timestamp = self._get_timestamp_prefix()
        safe_task_name = task_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        s3_key = (
            f"{self.s3_artifact_prefix}/{task_source}/{safe_task_name}/"
            f"{timestamp}_{local_path.name}"
        )
        return self.upload_file_to_s3(local_path, s3_key)

    def upload_conversation(
        self,
        conversation_history: list,
        task_name: str,
        task_source: str = "",
        additional_metadata: dict = None,
    ) -> Optional[str]:
        import tempfile

        timestamp = self._get_timestamp_prefix()
        safe_task_name = task_name.replace("/", "_").replace("\\", "_").replace(" ", "_")

        data = {
            "task_name": task_name,
            "task_source": task_source,
            "timestamp": datetime.now().isoformat(),
            "agent_model_name": self.agent_model_name,
            "agent_model_type": self.agent_model_type,
            "messages": conversation_history,
        }
        if additional_metadata:
            data["metadata"] = additional_metadata

        temp_path = Path(tempfile.gettempdir()) / f"conversation_{timestamp}_{safe_task_name}.json"
        try:
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            s3_key = f"{self.s3_conversation_prefix}/{timestamp}_{safe_task_name}.json"
            return self.upload_file_to_s3(temp_path, s3_key)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def save_to_database(
        self,
        task_name: str,
        task_source: str,
        artifact_s3_uris: list,
        conversation_s3_uri: Optional[str],
        start_time: datetime,
        end_time: datetime,
        cost: Optional[float] = None,
        task_id: int = None,
    ) -> Optional[int]:
        if not self.db_enabled:
            logger.info("Database saving disabled, skipping")
            return None

        try:
            from autowebprompt.storage.models import Task, TaskAttempt, get_session
        except ImportError:
            logger.warning("Database modules not available — install with: pip install autowebprompt[storage]")
            return None

        try:
            session = get_session()
            if session is None:
                logger.warning("No database connection — skipping save")
                return None

            time_taken_mins = None
            if start_time and end_time:
                time_taken_mins = (end_time - start_time).total_seconds() / 60

            if task_id:
                task = session.query(Task).filter(Task.id == task_id).first()
                if not task:
                    logger.warning(f"Task ID {task_id} not found in database")
                    return None
            else:
                task = session.query(Task).filter(
                    Task.task_name == task_name,
                    Task.task_source == task_source,
                ).first()
                if not task:
                    logger.warning(f"Task not found in database: {task_name}")
                    return None

            prompt_files = [conversation_s3_uri] if conversation_s3_uri else []

            attempt = TaskAttempt(
                task_id=task.id,
                prompt_files=prompt_files,
                start_end_times=[[
                    start_time.isoformat() if start_time else None,
                    end_time.isoformat() if end_time else None,
                ]],
                agent_model_name=self.agent_model_name,
                agent_model_type=self.agent_model_type,
                attempt_files=artifact_s3_uris or [],
                time_taken_mins=time_taken_mins,
                cost=cost,
            )
            session.add(attempt)
            session.commit()

            logger.info(f"Created TaskAttempt ID: {attempt.id}")
            return attempt.id

        except Exception as e:
            logger.error(f"Database save failed: {e}")
            return None

    def upload_results(
        self,
        task_name: str,
        task_source: str,
        artifact_paths: list = None,
        conversation_history: list = None,
        start_time: datetime = None,
        end_time: datetime = None,
        cost: Optional[float] = None,
        additional_metadata: dict = None,
        task_id: int = None,
    ) -> dict:
        result = {
            "success": True,
            "artifact_s3_uris": [],
            "conversation_s3_uri": None,
            "attempt_id": None,
            "errors": [],
        }

        logger.info(f"Uploading results for task: {task_name}")

        if artifact_paths:
            for path in artifact_paths:
                s3_uri = self.upload_artifact(path, task_name, task_source)
                if s3_uri:
                    result["artifact_s3_uris"].append(s3_uri)
                else:
                    result["errors"].append(f"Failed to upload artifact: {path}")

        if conversation_history:
            result["conversation_s3_uri"] = self.upload_conversation(
                conversation_history, task_name, task_source, additional_metadata,
            )
            if not result["conversation_s3_uri"]:
                result["errors"].append("Failed to upload conversation")

        if self.db_enabled:
            result["attempt_id"] = self.save_to_database(
                task_id=task_id,
                task_name=task_name,
                task_source=task_source,
                artifact_s3_uris=result["artifact_s3_uris"],
                conversation_s3_uri=result["conversation_s3_uri"],
                start_time=start_time or datetime.now(),
                end_time=end_time or datetime.now(),
                cost=cost,
            )

        result["success"] = len(result["errors"]) == 0
        return result
