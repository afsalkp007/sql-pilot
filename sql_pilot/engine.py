"""
SQLPilot Execution Engine.
Orchestrates schema introspection, SQL generation, firewall guardrail checks,
and autonomous self-healing query repair retry loops.
"""

import time
from typing import Optional

from .models import SQLPilotResponse, QueryRepairAttempt, QueryResult
from .database import DatabaseManager
from .firewall import validate_sql_safety
from .providers import BaseSQLProvider, GeminiSQLProvider, OpenAISQLProvider, MockSQLProvider
import os


class SQLPilotEngine:
    """
    Autonomous Text-to-SQL engine with self-healing query repair and safety guardrails.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseManager] = None,
        provider: Optional[BaseSQLProvider] = None,
        max_repair_retries: int = 2
    ):
        self.db = db_manager or DatabaseManager()
        self.provider = provider or self._auto_detect_provider()
        self.max_repair_retries = max_repair_retries

    def _auto_detect_provider(self) -> BaseSQLProvider:
        prov = os.getenv("LLM_PROVIDER", "").lower()
        if prov == "gemini" and os.getenv("GEMINI_API_KEY"):
            return GeminiSQLProvider()
        elif prov == "openai" and os.getenv("OPENAI_API_KEY"):
            return OpenAISQLProvider()
        elif os.getenv("GEMINI_API_KEY"):
            return GeminiSQLProvider()
        elif os.getenv("OPENAI_API_KEY"):
            return OpenAISQLProvider()
        return MockSQLProvider()

    def run(self, user_question: str) -> SQLPilotResponse:
        """
        Execute end-to-end question translation, safety validation, execution,
        and self-healing error recovery.
        """
        start_time = time.perf_counter()
        schema_context = self.db.format_schema_for_prompt()

        # 1. Generate Initial SQL
        generation = self.provider.generate_sql(user_question, schema_context)
        current_sql = generation.sql_query
        assumptions = list(generation.assumptions)
        repairs = []

        # 2. Safety Firewall Validation
        is_safe, violation_reason = validate_sql_safety(current_sql)
        if not is_safe:
            total_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return SQLPilotResponse(
                user_query=user_question,
                final_sql=current_sql,
                result=None,
                business_summary=f"Query Execution Blocked: {violation_reason}",
                assumptions_made=assumptions,
                repairs=[],
                is_blocked_by_guardrail=True,
                guardrail_reason=violation_reason,
                total_latency_ms=total_ms
            )

        # 3. Execution & Self-Healing Loop
        result: Optional[QueryResult] = None
        attempt = 0

        while attempt <= self.max_repair_retries:
            try:
                result = self.db.execute_query(current_sql)
                # Success!
                break
            except Exception as e:
                attempt += 1
                error_msg = str(e)

                if attempt > self.max_repair_retries:
                    # Retries exhausted
                    total_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    return SQLPilotResponse(
                        user_query=user_question,
                        final_sql=current_sql,
                        result=None,
                        business_summary=f"Execution Failed: Unable to repair query after {self.max_repair_retries} attempts ({error_msg}).",
                        assumptions_made=assumptions,
                        repairs=repairs,
                        is_blocked_by_guardrail=False,
                        guardrail_reason=None,
                        total_latency_ms=total_ms
                    )

                # Trigger Self-Healing Repair
                repaired_sql, fix_explanation = self.provider.repair_sql(
                    query=user_question,
                    failed_sql=current_sql,
                    error_message=error_msg,
                    schema_context=schema_context
                )

                repairs.append(QueryRepairAttempt(
                    attempt_number=attempt,
                    failed_sql=current_sql,
                    error_message=error_msg,
                    repaired_sql=repaired_sql,
                    fix_explanation=fix_explanation
                ))

                # Re-validate repaired SQL with firewall
                safe_repaired, rep_reason = validate_sql_safety(repaired_sql)
                if not safe_repaired:
                    total_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    return SQLPilotResponse(
                        user_query=user_question,
                        final_sql=repaired_sql,
                        result=None,
                        business_summary=f"Self-healed query violated security policy: {rep_reason}",
                        assumptions_made=assumptions,
                        repairs=repairs,
                        is_blocked_by_guardrail=True,
                        guardrail_reason=rep_reason,
                        total_latency_ms=total_ms
                    )

                current_sql = repaired_sql

        # 4. Generate Business Summary
        summary = self.provider.generate_business_summary(user_question, current_sql, result)
        total_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return SQLPilotResponse(
            user_query=user_question,
            final_sql=current_sql,
            result=result,
            business_summary=summary,
            assumptions_made=assumptions,
            repairs=repairs,
            is_blocked_by_guardrail=False,
            guardrail_reason=None,
            total_latency_ms=total_ms
        )
