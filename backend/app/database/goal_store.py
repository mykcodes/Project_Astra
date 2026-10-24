"""
ASTRA Durable Goal Checkpoint Store (Phase B.9)

Provides local-first, durable SQLite persistence for GoalCheckpoints.
Ensures goal execution progress survives unexpected backend termination,
supports atomic updates, validated recovery, and graceful corruption handling.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.logging.logger import get_logger
from app.domain.checkpoints import GoalCheckpoint, SCHEMA_VERSION
from app.domain.goals import GoalState


logger = get_logger(__name__)


class CheckpointError(Exception):
    """Base exception for checkpoint persistence failures."""
    pass


class CheckpointCorruptionError(CheckpointError):
    """Raised when persisted checkpoint data is corrupted or fails schema validation."""
    pass


class CheckpointNotFoundError(CheckpointError):
    """Raised when an expected checkpoint is not found."""
    pass


class SQLiteGoalStore:
    """
    Durable local-first SQLite persistence store for GoalCheckpoints.
    Utilizes WAL mode for transactional atomicity and multi-threaded safety.
    """

    def __init__(self, db_path: str = "astra_goals.db"):
        self.db_path = db_path
        self._lock = threading.RLock()
        
        # Prepare parent directory if path is a file in a subfolder
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None, # Explicit transaction control
        )
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode and foreign keys for durability and crash safety
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")
        
        self._init_schema()

    def _init_schema(self) -> None:
        """Initializes the checkpoint persistence schema."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS goal_checkpoints (
                        goal_id TEXT PRIMARY KEY,
                        checkpoint_id TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        goal_state TEXT NOT NULL,
                        current_task_index INTEGER NOT NULL,
                        is_resumable INTEGER NOT NULL,
                        checkpoint_data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_goal_checkpoints_resumable
                    ON goal_checkpoints (is_resumable, updated_at DESC);
                    """
                )

    def save_checkpoint(self, checkpoint: GoalCheckpoint) -> None:
        """
        Atomically saves or updates a GoalCheckpoint.
        Serializes data as JSON and writes within an atomic transaction.
        """
        with self._lock:
            try:
                raw_json = checkpoint.model_dump_json()
                created_iso = checkpoint.created_at.isoformat()
                updated_iso = checkpoint.updated_at.isoformat()
                is_res = 1 if checkpoint.is_resumable else 0

                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO goal_checkpoints (
                            goal_id, checkpoint_id, schema_version, goal_state,
                            current_task_index, is_resumable, checkpoint_data,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(goal_id) DO UPDATE SET
                            checkpoint_id = excluded.checkpoint_id,
                            schema_version = excluded.schema_version,
                            goal_state = excluded.goal_state,
                            current_task_index = excluded.current_task_index,
                            is_resumable = excluded.is_resumable,
                            checkpoint_data = excluded.checkpoint_data,
                            updated_at = excluded.updated_at;
                        """,
                        (
                            checkpoint.goal_id,
                            checkpoint.checkpoint_id,
                            checkpoint.schema_version,
                            checkpoint.goal_state.value,
                            checkpoint.current_task_index,
                            is_res,
                            raw_json,
                            created_iso,
                            updated_iso,
                        ),
                    )
            except Exception as e:
                logger.error(f"Failed to persist GoalCheckpoint '{checkpoint.goal_id}': {e}")
                raise CheckpointError(f"Database error saving checkpoint '{checkpoint.goal_id}': {e}") from e

    def get_checkpoint(self, goal_id: str) -> Optional[GoalCheckpoint]:
        """
        Retrieves and validates a GoalCheckpoint by goal_id.
        Fails safely if record is corrupted or schema version is unsupported.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT checkpoint_data FROM goal_checkpoints WHERE goal_id = ?;",
                (goal_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            raw_data = row["checkpoint_data"]
            try:
                parsed = json.loads(raw_data)
                cp = GoalCheckpoint(**parsed)
                return cp
            except Exception as e:
                logger.error(f"Checkpoint data corruption detected for goal '{goal_id}': {e}")
                raise CheckpointCorruptionError(
                    f"Corrupted or invalid checkpoint data for goal '{goal_id}': {e}"
                ) from e

    def list_resumable_goals(self, limit: int = 50) -> List[GoalCheckpoint]:
        """
        Returns all goals currently eligible for resumption, ordered by recent activity.
        Excludes completed or explicitly cancelled goals.
        """
        with self._lock:
            cursor = self._conn.execute(
                """
                SELECT checkpoint_data FROM goal_checkpoints
                WHERE is_resumable = 1
                  AND goal_state NOT IN ('COMPLETED', 'CANCELLED')
                ORDER BY updated_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()

            resumable_list: List[GoalCheckpoint] = []
            for row in rows:
                try:
                    parsed = json.loads(row["checkpoint_data"])
                    cp = GoalCheckpoint(**parsed)
                    valid, reason = cp.validate_resumable()
                    if valid:
                        resumable_list.append(cp)
                    else:
                        logger.warning(f"Excluding invalid resumable goal '{cp.goal_id}': {reason}")
                except Exception as e:
                    logger.warning(f"Skipping corrupted checkpoint record during listing: {e}")
                    continue

            return resumable_list

    def list_all_checkpoints(self, limit: int = 100) -> List[GoalCheckpoint]:
        """Returns all persisted checkpoints regardless of state."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT checkpoint_data FROM goal_checkpoints ORDER BY updated_at DESC LIMIT ?;",
                (limit,),
            )
            rows = cursor.fetchall()
            all_list = []
            for row in rows:
                try:
                    parsed = json.loads(row["checkpoint_data"])
                    all_list.append(GoalCheckpoint(**parsed))
                except Exception as e:
                    logger.warning(f"Skipping corrupted record: {e}")
            return all_list

    def mark_non_resumable(self, goal_id: str, reason: Optional[str] = None) -> bool:
        """
        Permanently marks a goal checkpoint as non-resumable (e.g. on unrecoverable abort or rollback).
        """
        with self._lock:
            cp = self.get_checkpoint(goal_id)
            if not cp:
                return False
            cp.is_resumable = False
            if reason:
                cp.suspension_reason = reason
            self.save_checkpoint(cp)
            return True

    def delete_checkpoint(self, goal_id: str) -> bool:
        """Deletes a checkpoint record by goal_id."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM goal_checkpoints WHERE goal_id = ?;",
                    (goal_id,),
                )
                return cursor.rowcount > 0

    def close(self) -> None:
        """Closes the database connection safely."""
        with self._lock:
            try:
                self._conn.close()
            except Exception as e:
                logger.debug(f"Error closing SQLite goal store: {e}")


# Type alias for general store contract
GoalStore = SQLiteGoalStore

# Global default store instance
_default_store: Optional[SQLiteGoalStore] = None
_store_lock = threading.Lock()


def get_goal_store(db_path: str = "astra_goals.db") -> SQLiteGoalStore:
    """Returns the singleton or newly instantiated SQLiteGoalStore."""
    global _default_store
    with _store_lock:
        if _default_store is None:
            _default_store = SQLiteGoalStore(db_path=db_path)
        return _default_store
