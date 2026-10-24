"""
ASTRA Durable Local Memory Store (Phase B.10)

Provides local-first, durable SQLite persistence for cross-session memories,
user facts/preferences, application profiles, and episodic goal run summaries.
Supports Write-Ahead Logging (WAL mode), atomic transactions, relevance search,
and safe corruption handling.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging.logger import get_logger
from app.domain.memory import (
    MEMORY_SCHEMA_VERSION,
    MemoryType,
    ProvenanceType,
    MemoryRecord,
    ApplicationProfile,
    EpisodicGoalSummary,
    MemoryQuery,
    MemorySearchResult,
)


logger = get_logger(__name__)


class MemoryStoreError(Exception):
    """Base exception for memory store persistence failures."""
    pass


class MemoryCorruptionError(MemoryStoreError):
    """Raised when persisted memory data is corrupted or fails schema validation."""
    pass


class MemoryNotFoundError(MemoryStoreError):
    """Raised when an expected memory record or profile is not found."""
    pass


class SQLiteMemoryStore:
    """
    Durable local-first SQLite persistence store for ASTRA's memory layers.
    Operates in WAL mode with synchronous transactions for crash survivability.
    """

    def __init__(self, db_path: str = "astra_memory.db"):
        self.db_path = db_path
        self._lock = threading.RLock()

        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # Explicit transaction control
        )
        self._conn.row_factory = sqlite3.Row

        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL;")
            self._conn.execute("PRAGMA synchronous = NORMAL;")
        self._conn.execute("PRAGMA foreign_keys = ON;")

        self._init_schema()

    def _init_schema(self) -> None:
        """Initializes tables and indexes for memory records and application profiles."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_records (
                        memory_id TEXT PRIMARY KEY,
                        schema_version TEXT NOT NULL,
                        memory_type TEXT NOT NULL,
                        key TEXT UNIQUE NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        metadata TEXT NOT NULL,
                        provenance TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        access_count INTEGER NOT NULL DEFAULT 0,
                        last_accessed_at TEXT,
                        record_data TEXT NOT NULL
                    );
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS application_profiles (
                        canonical_name TEXT PRIMARY KEY,
                        app_name TEXT NOT NULL,
                        category TEXT NOT NULL,
                        aliases TEXT NOT NULL,
                        is_preferred INTEGER NOT NULL DEFAULT 0,
                        profile_data TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                # Indexes for fast retrieval
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_records_type
                    ON memory_records (memory_type, updated_at DESC);
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_memory_records_key
                    ON memory_records (key);
                    """
                )
                self._conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_app_profiles_cat
                    ON application_profiles (category, is_preferred DESC);
                    """
                )

    # =========================================================================
    # MemoryRecord Operations
    # =========================================================================

    def save_record(self, record: MemoryRecord) -> None:
        """
        Atomically saves or updates a MemoryRecord.
        Prevents duplicate records through atomic upsert on unique key.
        Increments revision version upon updating existing records.
        """
        with self._lock:
            try:
                # Check for existing record to bump revision version
                cursor = self._conn.execute(
                    "SELECT record_data FROM memory_records WHERE key = ?;",
                    (record.key,),
                )
                existing_row = cursor.fetchone()
                if existing_row:
                    old_rec = self._deserialize_record(existing_row["record_data"], record.key)
                    if old_rec:
                        record.version = old_rec.version + 1
                        if record.access_count == 0 and old_rec.access_count > 0:
                            record.access_count = old_rec.access_count

                record_json = record.to_json()
                tags_json = json.dumps(record.tags)
                meta_json = json.dumps(record.metadata)
                created_iso = record.created_at.isoformat()
                updated_iso = record.updated_at.isoformat()
                last_accessed_iso = record.last_accessed_at.isoformat() if record.last_accessed_at else None

                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO memory_records (
                            memory_id, schema_version, memory_type, key, content,
                            tags, metadata, provenance, confidence, created_at,
                            updated_at, access_count, last_accessed_at, record_data
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            memory_id = excluded.memory_id,
                            schema_version = excluded.schema_version,
                            memory_type = excluded.memory_type,
                            content = excluded.content,
                            tags = excluded.tags,
                            metadata = excluded.metadata,
                            provenance = excluded.provenance,
                            confidence = excluded.confidence,
                            updated_at = excluded.updated_at,
                            access_count = excluded.access_count,
                            last_accessed_at = excluded.last_accessed_at,
                            record_data = excluded.record_data;
                        """,
                        (
                            record.memory_id,
                            record.schema_version,
                            record.memory_type.value,
                            record.key,
                            record.content,
                            tags_json,
                            meta_json,
                            record.provenance.value,
                            record.confidence,
                            created_iso,
                            updated_iso,
                            record.access_count,
                            last_accessed_iso,
                            record_json,
                        ),
                    )
            except Exception as e:
                logger.error(f"Failed to save MemoryRecord '{record.key}': {e}")
                raise MemoryStoreError(f"Database error saving memory record '{record.key}': {e}") from e

    def put_record(self, record: MemoryRecord) -> MemoryRecord:
        """Atomically saves or updates a MemoryRecord and returns it."""
        self.save_record(record)
        return record

    def get_record(self, identifier: str) -> Optional[MemoryRecord]:
        """Retrieves a MemoryRecord by memory_id or unique key, failing safely on corruption."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT record_data FROM memory_records WHERE memory_id = ? OR key = ?;",
                (identifier, identifier),
            )
            row = cursor.fetchone()
            if not row:
                return None
            rec = self._deserialize_record(row["record_data"], identifier)
            if rec:
                # Increment access count and record access timestamp
                rec.access_count += 1
                rec.last_accessed_at = datetime.now(timezone.utc)
                with self._conn:
                    self._conn.execute(
                        "UPDATE memory_records SET access_count = ?, last_accessed_at = ?, record_data = ? WHERE memory_id = ?;",
                        (rec.access_count, rec.last_accessed_at.isoformat(), rec.to_json(), rec.memory_id),
                    )
            return rec

    def get_record_by_key(self, key: str) -> Optional[MemoryRecord]:
        """Retrieves a MemoryRecord by semantic key."""
        return self.get_record(key)

    def delete_record(self, identifier: str) -> bool:
        """Deletes a MemoryRecord by memory_id or unique key."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM memory_records WHERE memory_id = ? OR key = ?;",
                    (identifier, identifier),
                )
                return cursor.rowcount > 0

    def delete_record_by_key(self, key: str) -> bool:
        """Deletes a MemoryRecord by unique key."""
        return self.delete_record(key)

    def list_records(
        self,
        memory_type: Optional[MemoryType] = None,
        tag: Optional[str] = None,
        limit: int = 100,
    ) -> List[MemoryRecord]:
        """Lists records with optional filtering by MemoryType and tag."""
        with self._lock:
            query = "SELECT record_data FROM memory_records"
            params: List[Any] = []
            conditions: List[str] = []

            if memory_type:
                conditions.append("memory_type = ?")
                params.append(memory_type.value)
            if tag:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY updated_at DESC LIMIT ?;"
            params.append(limit)

            cursor = self._conn.execute(query, tuple(params))
            records: List[MemoryRecord] = []
            for row in cursor.fetchall():
                rec = self._deserialize_record(row["record_data"], "list")
                if rec:
                    records.append(rec)
            return records

    def search_records(self, query: MemoryQuery) -> List[MemorySearchResult]:
        """
        Performs local token-based keyword search with relevance ranking.
        Does not require external vector databases or paid embedding APIs.
        """
        with self._lock:
            # Tokenize search text into distinct alphanumeric terms
            tokens = [t.lower() for t in re.findall(r"\w+", query.query_text) if len(t) > 1]
            if not tokens:
                return []

            candidate_records = self.list_records(
                memory_type=query.memory_types[0] if query.memory_types and len(query.memory_types) == 1 else None,
                limit=100,
            )

            results: List[MemorySearchResult] = []
            now = datetime.now(timezone.utc)

            for rec in candidate_records:
                # Filter by allowed memory types
                if query.memory_types and rec.memory_type not in query.memory_types:
                    continue
                # Filter by required tags
                if query.tags and not any(t in rec.tags for t in query.tags):
                    continue

                score = 0.0
                matched_tokens: List[str] = []
                key_lower = rec.key.lower()
                content_lower = rec.content.lower()
                tags_lower = [t.lower() for t in rec.tags]

                for token in tokens:
                    token_matched = False
                    # Key match (highest relevance: 5.0)
                    if token in key_lower:
                        score += 5.0
                        token_matched = True
                    # Tag match (high relevance: 3.0)
                    if any(token in t for t in tags_lower):
                        score += 3.0
                        token_matched = True
                    # Content term match (relevance: 1.0)
                    if token in content_lower:
                        # Frequency bonus in content
                        occurrences = content_lower.count(token)
                        score += min(1.0 + (occurrences - 1) * 0.2, 2.0)
                        token_matched = True

                    if token_matched:
                        matched_tokens.append(token)

                if score > 0.0 and score >= query.min_score:
                    # Provenance boost: user explicit facts get a 20% boost
                    if rec.provenance in (ProvenanceType.USER_EXPLICIT, ProvenanceType.USER_PREFERENCE):
                        score *= 1.2
                    # Access frequency boost (up to +0.5)
                    score += min(rec.access_count * 0.05, 0.5)

                    results.append(
                        MemorySearchResult(
                            record=rec,
                            score=round(score, 3),
                            matched_tokens=matched_tokens,
                        )
                    )

            # Sort by score descending, access count descending
            results.sort(key=lambda r: (r.score, r.record.access_count), reverse=True)
            top_results = results[: query.limit]

            # Increment access audit for returned results
            for res in top_results:
                self.touch_record(res.record.memory_id)

            return top_results

    def search(self, query: MemoryQuery) -> List[MemorySearchResult]:
        """Alias for search_records."""
        return self.search_records(query)

    def touch_record(self, memory_id: str) -> None:
        """Increments access count and updates last_accessed_at timestamp."""
        with self._lock:
            with self._conn:
                now_iso = datetime.now(timezone.utc).isoformat()
                self._conn.execute(
                    """
                    UPDATE memory_records
                    SET access_count = access_count + 1,
                        last_accessed_at = ?
                    WHERE memory_id = ?;
                    """,
                    (now_iso, memory_id),
                )

    def _deserialize_record(self, raw_json: str, identifier: str) -> Optional[MemoryRecord]:
        try:
            return MemoryRecord.from_json(raw_json)
        except Exception as e:
            logger.error(f"Memory corruption detected for record '{identifier}': {e}")
            raise MemoryCorruptionError(f"Corrupted memory record '{identifier}': {e}") from e

    # =========================================================================
    # ApplicationProfile Operations
    # =========================================================================

    def save_profile(self, profile: ApplicationProfile) -> None:
        """Atomically saves or updates an ApplicationProfile."""
        with self._lock:
            try:
                prof_json = profile.to_dict()
                raw_json = json.dumps(prof_json)
                aliases_json = json.dumps([a.lower().strip() for a in profile.aliases])
                updated_iso = profile.updated_at.isoformat()
                is_pref = 1 if profile.is_preferred else 0

                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO application_profiles (
                            canonical_name, app_name, category, aliases,
                            is_preferred, profile_data, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_name) DO UPDATE SET
                            app_name = excluded.app_name,
                            category = excluded.category,
                            aliases = excluded.aliases,
                            is_preferred = excluded.is_preferred,
                            profile_data = excluded.profile_data,
                            updated_at = excluded.updated_at;
                        """,
                        (
                            profile.canonical_name.lower().strip(),
                            profile.app_name,
                            profile.category.lower().strip(),
                            aliases_json,
                            is_pref,
                            raw_json,
                            updated_iso,
                        ),
                    )
            except Exception as e:
                logger.error(f"Failed to save ApplicationProfile '{profile.canonical_name}': {e}")
                raise MemoryStoreError(f"Database error saving profile '{profile.canonical_name}': {e}") from e

    def get_profile(self, canonical_name: str) -> Optional[ApplicationProfile]:
        """Retrieves an ApplicationProfile by its canonical name."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT profile_data FROM application_profiles WHERE canonical_name = ?;",
                (canonical_name.lower().strip(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            try:
                data = json.loads(row["profile_data"])
                return ApplicationProfile.from_dict(data)
            except Exception as e:
                logger.error(f"Profile corruption detected for '{canonical_name}': {e}")
                raise MemoryCorruptionError(f"Corrupted profile '{canonical_name}': {e}") from e

    def list_profiles(self, category: Optional[str] = None) -> List[ApplicationProfile]:
        """Lists application profiles, optionally filtered by category."""
        with self._lock:
            query = "SELECT profile_data FROM application_profiles"
            params: List[Any] = []
            if category:
                query += " WHERE category = ?"
                params.append(category.lower().strip())
            query += " ORDER BY is_preferred DESC, canonical_name ASC;"

            cursor = self._conn.execute(query, tuple(params))
            profiles: List[ApplicationProfile] = []
            for row in cursor.fetchall():
                try:
                    data = json.loads(row["profile_data"])
                    profiles.append(ApplicationProfile.from_dict(data))
                except Exception as e:
                    logger.warning(f"Skipping corrupted profile: {e}")
            return profiles

    def find_profile_by_alias(self, alias: str, category: Optional[str] = None) -> Optional[ApplicationProfile]:
        """
        Resolves a natural-language alias (e.g. 'my browser', 'notes') to an ApplicationProfile.
        Prioritizes category matches and user-preferred profiles.
        """
        norm_alias = alias.lower().strip()
        candidates = self.list_profiles(category=category)

        # 1. Exact match on canonical_name or app_name
        for p in candidates:
            if p.canonical_name == norm_alias or p.app_name.lower() == norm_alias:
                return p

        # 2. Match within aliases list
        alias_matches: List[ApplicationProfile] = []
        for p in candidates:
            if any(norm_alias == a.lower() or norm_alias in a.lower() for a in p.aliases):
                alias_matches.append(p)

        if alias_matches:
            # If multiple match, prefer the one explicitly flagged as preferred
            for p in alias_matches:
                if p.is_preferred:
                    return p
            return alias_matches[0]

        # 3. If category filter was specified and alias is the category name itself (e.g. 'browser')
        if category and norm_alias in (category, f"my {category}", f"default {category}"):
            for p in candidates:
                if p.is_preferred:
                    return p
            if candidates:
                return candidates[0]

        return None

    def delete_profile(self, canonical_name: str) -> bool:
        """Deletes an ApplicationProfile by canonical name."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM application_profiles WHERE canonical_name = ?;",
                    (canonical_name.lower().strip(),),
                )
                return cursor.rowcount > 0

    # =========================================================================
    # Episodic Goal Summaries
    # =========================================================================

    def save_episodic_summary(self, summary: EpisodicGoalSummary) -> MemoryRecord:
        """Persists a verified goal execution summary into episodic memory."""
        record = MemoryRecord(
            memory_type=MemoryType.EPISODIC,
            key=f"episode:{summary.goal_id}",
            content=summary.summary_text,
            tags=["episode", "goal_summary"] + summary.touched_applications,
            metadata=summary.model_dump(mode="json"),
            provenance=ProvenanceType.EPISODIC_SUMMARY,
            confidence=1.0,
        )
        self.save_record(record)
        return record

    def list_episodic_summaries(self, limit: int = 20) -> List[EpisodicGoalSummary]:
        """Lists historical episodic goal summaries in reverse chronological order."""
        records = self.list_records(memory_type=MemoryType.EPISODIC, limit=limit)
        summaries: List[EpisodicGoalSummary] = []
        for r in records:
            try:
                summaries.append(EpisodicGoalSummary(**r.metadata))
            except Exception as e:
                logger.warning(f"Skipping corrupted episodic summary in record '{r.key}': {e}")
        return summaries

    def close(self) -> None:
        """Closes the SQLite database connection safely."""
        with self._lock:
            try:
                self._conn.close()
            except Exception as e:
                logger.debug(f"Error closing SQLite memory store: {e}")


# Global default store instance
MemoryStore = SQLiteMemoryStore
_default_memory_store: Optional[SQLiteMemoryStore] = None
_store_lock = threading.Lock()


def get_memory_store(db_path: str = "astra_memory.db") -> SQLiteMemoryStore:
    """Returns the singleton or newly initialized SQLiteMemoryStore."""
    global _default_memory_store
    with _store_lock:
        if _default_memory_store is None:
            _default_memory_store = SQLiteMemoryStore(db_path=db_path)
        return _default_memory_store
