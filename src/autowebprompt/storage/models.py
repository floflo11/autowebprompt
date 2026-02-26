"""
Database models for autowebprompt — optional PostgreSQL storage.

Install with: pip install autowebprompt[storage]
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_Session = None


def get_session():
    """Get a database session. Returns None if not configured."""
    global _Session

    if _Session is None:
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            logger.debug("DATABASE_URL not set — database features disabled")
            return None

        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            engine = create_engine(database_url)
            _Session = sessionmaker(bind=engine)
        except ImportError:
            logger.warning("sqlalchemy not installed — install with: pip install autowebprompt[storage]")
            return None
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return None

    try:
        return _Session()
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        return None


# Lazy model definitions — only created when SQLAlchemy is available
def _define_models():
    """Define SQLAlchemy models. Called lazily to avoid import errors."""
    try:
        from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Text
        from sqlalchemy.orm import DeclarativeBase, relationship
        from sqlalchemy.sql import func
    except ImportError:
        return None, None

    class Base(DeclarativeBase):
        pass

    class Task(Base):
        __tablename__ = "tasks"

        id = Column(Integer, primary_key=True)
        task_name = Column(String, nullable=False)
        task_starting_files = Column(JSON)
        task_solution_files = Column(JSON)
        task_source = Column(String)
        accuracy_compatible = Column(Boolean, default=True)
        format_compatible = Column(Boolean, default=True)
        usability_compatible = Column(Boolean, default=True)
        deprecated = Column(Boolean, default=False)
        deprecation_reason = Column(Text)
        created_at = Column(DateTime, server_default=func.now())
        updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    class TaskAttempt(Base):
        __tablename__ = "task_attempts"

        id = Column(Integer, primary_key=True)
        task_id = Column(Integer, ForeignKey("tasks.id"))
        prompt_files = Column(JSON)
        start_end_times = Column(JSON)
        agent_model_name = Column(String)
        agent_model_type = Column(String)
        attempt_files = Column(JSON)
        time_taken_mins = Column(Float)
        cost = Column(Float)
        created_at = Column(DateTime, server_default=func.now())

    return Task, TaskAttempt


# Module-level lazy initialization
_models_defined = False
Task = None
TaskAttempt = None


def _ensure_models():
    global _models_defined, Task, TaskAttempt
    if not _models_defined:
        result = _define_models()
        if result:
            Task, TaskAttempt = result
        _models_defined = True


_ensure_models()
