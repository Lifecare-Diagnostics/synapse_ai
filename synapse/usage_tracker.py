"""
synapse_poc/synapse/usage_tracker.py
API usage tracking and cost estimation for LLM providers.
Stores per-call usage records in SQLite for dashboard display and cost analysis.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


# ----- Pricing Constants (USD per 1M tokens) -----
# These are illustrative rates for the POC cost calculator.
# Update when official pricing changes. Do NOT rely on these for billing.
PRICING = {
    "gemini-3.5-flash-lite": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-3.1-flash-lite": {"input_per_1m": 0.10, "output_per_1m": 0.40},
    "gemini-4-hydrogen": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    # Ollama / Mock are free (local)
    "default": {"input_per_1m": 0.10, "output_per_1m": 0.40},
}

# INR exchange rate for Indian cost estimates
USD_TO_INR = 90.0


def estimate_cost_usd(
    model: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
) -> float:
    """Estimate cost in USD for a single API call."""
    rates = PRICING.get(model, PRICING["default"])
    inp = (input_tokens or 0) / 1_000_000 * rates["input_per_1m"]
    out = (output_tokens or 0) / 1_000_000 * rates["output_per_1m"]
    return round(inp + out, 8)


class UsageTracker:
    """
    Thread-safe LLM usage tracker backed by SQLite.
    Records per-call token usage and provides aggregated summaries.
    """

    _CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS llm_usage (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        document_id TEXT,
        input_tokens INTEGER,
        output_tokens INTEGER,
        total_tokens INTEGER,
        estimated_cost_usd REAL,
        status TEXT,
        processing_time_seconds REAL
    );
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute(self._CREATE_TABLE)
            conn.commit()
            if self._mem_conn is None:
                conn.close()

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        document_id: Optional[str] = None,
        status: str = "success",
        processing_time_seconds: Optional[float] = None,
    ) -> str:
        """Record a single LLM API usage event. Returns the record ID."""
        record_id = str(uuid.uuid4())[:12]
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO llm_usage
                   (id, provider, model, timestamp, document_id,
                    input_tokens, output_tokens, total_tokens,
                    estimated_cost_usd, status, processing_time_seconds)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record_id, provider, model, ts, document_id,
                    input_tokens, output_tokens, total_tokens,
                    cost, status, processing_time_seconds,
                ),
            )
            conn.commit()
            if self._mem_conn is None:
                conn.close()
        return record_id

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregate usage summary across all providers."""
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                """SELECT
                       COUNT(*) as total_calls,
                       COALESCE(SUM(input_tokens), 0) as total_input_tokens,
                       COALESCE(SUM(output_tokens), 0) as total_output_tokens,
                       COALESCE(SUM(total_tokens), 0) as total_all_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost_usd,
                       COALESCE(AVG(processing_time_seconds), 0.0) as avg_processing_time
                   FROM llm_usage WHERE status = 'success'"""
            ).fetchone()

            by_provider = conn.execute(
                """SELECT provider, model,
                       COUNT(*) as calls,
                       COALESCE(SUM(input_tokens), 0) as input_tokens,
                       COALESCE(SUM(output_tokens), 0) as output_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0.0) as cost_usd
                   FROM llm_usage WHERE status = 'success'
                   GROUP BY provider, model"""
            ).fetchall()

            error_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM llm_usage WHERE status != 'success'"
            ).fetchone()["cnt"]

            recent = conn.execute(
                """SELECT id, provider, model, timestamp, document_id,
                       input_tokens, output_tokens, estimated_cost_usd,
                       status, processing_time_seconds
                   FROM llm_usage ORDER BY timestamp DESC LIMIT 20"""
            ).fetchall()

            if self._mem_conn is None:
                conn.close()

        return {
            "total_calls": row["total_calls"],
            "total_input_tokens": row["total_input_tokens"],
            "total_output_tokens": row["total_output_tokens"],
            "total_tokens": row["total_all_tokens"],
            "total_cost_usd": round(row["total_cost_usd"], 6),
            "total_cost_inr": round(row["total_cost_usd"] * USD_TO_INR, 2),
            "avg_processing_time_seconds": round(row["avg_processing_time"], 3),
            "error_count": error_count,
            "breakdown_by_provider": [
                {
                    "provider": r["provider"],
                    "model": r["model"],
                    "calls": r["calls"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "cost_usd": round(r["cost_usd"], 6),
                    "cost_inr": round(r["cost_usd"] * USD_TO_INR, 2),
                }
                for r in by_provider
            ],
            "recent_calls": [
                {
                    "id": r["id"],
                    "provider": r["provider"],
                    "model": r["model"],
                    "timestamp": r["timestamp"],
                    "document_id": r["document_id"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "estimated_cost_usd": r["estimated_cost_usd"],
                    "status": r["status"],
                    "processing_time_seconds": r["processing_time_seconds"],
                }
                for r in recent
            ],
        }

    def get_monthly_cost_estimate(
        self,
        documents_per_month: int,
        model: Optional[str] = None,
        avg_input_tokens: int = 5000,
        avg_output_tokens: int = 1000,
    ) -> Dict[str, Any]:
        """
        Calculate projected monthly cost for a given document volume.
        Uses configurable per-document token averages.
        """
        model_name = model or "gemini-3.5-flash-lite"
        total_input = documents_per_month * avg_input_tokens
        total_output = documents_per_month * avg_output_tokens
        cost_usd = estimate_cost_usd(model_name, total_input, total_output)

        return {
            "model": model_name,
            "documents_per_month": documents_per_month,
            "avg_input_tokens_per_doc": avg_input_tokens,
            "avg_output_tokens_per_doc": avg_output_tokens,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "estimated_monthly_cost_usd": round(cost_usd, 4),
            "estimated_monthly_cost_inr": round(cost_usd * USD_TO_INR, 2),
            "pricing_note": "Illustrative rates for POC planning. Verify with official Google pricing.",
        }


# Module-level default tracker (lazy singleton)
_default_tracker: Optional[UsageTracker] = None
_tracker_lock = threading.Lock()


def get_usage_tracker(db_path: Optional[str] = None) -> UsageTracker:
    """Get or create the default usage tracker singleton."""
    global _default_tracker
    with _tracker_lock:
        if _default_tracker is None:
            _default_tracker = UsageTracker(db_path or ":memory:")
    return _default_tracker
