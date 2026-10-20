"""
LLM Generation and Self-Healing Repair Providers for SQLPilot.
Includes Gemini, OpenAI, and a deterministic Mock provider with realistic query synthesis.
"""

from abc import ABC, abstractmethod
import json
import os
import re
import urllib.request
from typing import List, Tuple, Optional, Dict, Any

from .models import SQLGeneration, QueryResult

SYSTEM_SQL_PROMPT = """You are SQLPilot, an expert senior database architect and analytics engineer.
Your task is to convert business questions into valid, optimal SQL queries.

CRITICAL RULES:
1. READ-ONLY STRICT: Generate ONLY SELECT statements (or WITH CTEs followed by SELECT). Never write mutating queries.
2. DIALECT COMPATIBILITY: Generate standard SQLite-compatible SQL (use standard functions, strftime for dates, etc.).
3. COLUMN PRECISION: Rely ONLY on the tables and columns provided in the schema context. Do not invent columns.
4. EXPLICIT ASSUMPTIONS: If a business term is ambiguous (e.g. 'active subscription', 'high priority'), define your assumption in the 'assumptions' list.
5. FORMAT: Return pure JSON matching the requested schema.
"""


def clean_json_text(text: str) -> str:
    """Clean markdown code fences from LLM responses."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


class BaseSQLProvider(ABC):
    """Abstract interface for SQL generation, repair, and business summarization."""

    @abstractmethod
    def generate_sql(self, query: str, schema_context: str) -> SQLGeneration:
        """Translate natural language query into SQL."""
        pass

    @abstractmethod
    def repair_sql(
        self,
        query: str,
        failed_sql: str,
        error_message: str,
        schema_context: str
    ) -> Tuple[str, str]:
        """Self-healing: Given the database error traceback, generate corrected SQL and explanation."""
        pass

    @abstractmethod
    def generate_business_summary(self, query: str, sql: str, result: QueryResult) -> str:
        """Translate raw database results into an executive business answer."""
        pass


class GeminiSQLProvider(BaseSQLProvider):
    """Google Gemini 2.5 Flash implementation."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_MODEL", model)
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is required for GeminiSQLProvider.")

    def _call_gemini(self, prompt: str, json_mode: bool = True) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_SQL_PROMPT}]},
            "generationConfig": {"temperature": 0.0}
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    def generate_sql(self, query: str, schema_context: str) -> SQLGeneration:
        prompt = f"""Schema Context:
{schema_context}

User Question: "{query}"

Generate a valid SQLite query. Return JSON format:
{{
  "sql_query": "SELECT ...",
  "thought": "Step-by-step reasoning explaining table joins, filtering, and aggregation",
  "assumptions": ["List any assumptions about business terms"]
}}
"""
        raw = self._call_gemini(prompt, json_mode=True)
        data = json.loads(clean_json_text(raw))
        return SQLGeneration.model_validate(data)

    def repair_sql(
        self,
        query: str,
        failed_sql: str,
        error_message: str,
        schema_context: str
    ) -> Tuple[str, str]:
        prompt = f"""Schema Context:
{schema_context}

User Question: "{query}"

The following SQL query failed during database execution:
SQL: {failed_sql}
Database Error: {error_message}

Analyze the error and the schema context, fix the column name, join condition, or syntax error.
Return JSON format:
{{
  "repaired_sql": "SELECT ...",
  "fix_explanation": "Explanation of what was incorrect and how it was fixed"
}}
"""
        raw = self._call_gemini(prompt, json_mode=True)
        data = json.loads(clean_json_text(raw))
        return data.get("repaired_sql", failed_sql), data.get("fix_explanation", "Repaired query syntax.")

    def generate_business_summary(self, query: str, sql: str, result: QueryResult) -> str:
        prompt = f"""User Question: "{query}"
Executed SQL: {sql}
Result Summary: Returned {result.row_count} rows.
Columns: {result.columns}
Data (first 5 rows): {result.rows[:5]}

Provide a concise, executive business summary answering the user's question directly based on the data.
Format numbers and currency cleanly.
"""
        return self._call_gemini(prompt, json_mode=False)


class OpenAISQLProvider(BaseSQLProvider):
    """OpenAI GPT-4o-mini implementation."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("OPENAI_MODEL", model)
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAISQLProvider.")

    def _call_openai(self, prompt: str, json_mode: bool = True) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_SQL_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

    def generate_sql(self, query: str, schema_context: str) -> SQLGeneration:
        prompt = f"""Schema Context:
{schema_context}

User Question: "{query}"

Generate a valid SQLite query. Return JSON format:
{{
  "sql_query": "SELECT ...",
  "thought": "Reasoning",
  "assumptions": []
}}
"""
        raw = self._call_openai(prompt, json_mode=True)
        data = json.loads(clean_json_text(raw))
        return SQLGeneration.model_validate(data)

    def repair_sql(self, query: str, failed_sql: str, error_message: str, schema_context: str) -> Tuple[str, str]:
        prompt = f"""Schema Context: {schema_context}
Question: "{query}"
Failed SQL: {failed_sql}
Error: {error_message}

Fix the query. Return JSON:
{{ "repaired_sql": "SELECT ...", "fix_explanation": "..." }}
"""
        raw = self._call_openai(prompt, json_mode=True)
        data = json.loads(clean_json_text(raw))
        return data.get("repaired_sql", failed_sql), data.get("fix_explanation", "Repaired query.")

    def generate_business_summary(self, query: str, sql: str, result: QueryResult) -> str:
        prompt = f"Question: {query}\nSQL: {sql}\nData: {result.rows[:5]}\nAnswer executive business summary:"
        return self._call_openai(prompt, json_mode=False)


class MockSQLProvider(BaseSQLProvider):
    """
    Deterministic Mock Provider for offline testing, CI/CD, and instant evaluation.
    Includes built-in query mappings and realistic self-healing repair simulation.
    """

    def generate_sql(self, query: str, schema_context: str) -> SQLGeneration:
        q_lower = query.lower()

        # 1. MRR by plan tier
        if "mrr" in q_lower or "recurring revenue" in q_lower or "plan tier" in q_lower:
            return SQLGeneration(
                sql_query="""
                SELECT 
                    plan_name,
                    COUNT(*) AS active_subscriptions,
                    SUM(monthly_price_usd) AS mrr_usd
                FROM subscriptions
                WHERE status = 'active'
                GROUP BY plan_name
                ORDER BY mrr_usd DESC;
                """.strip(),
                thought="Group active subscriptions by plan_name and sum monthly_price_usd to calculate MRR.",
                assumptions=["MRR calculated strictly for subscriptions with status='active'."]
            )

        # 2. Top customers by spend
        elif "top" in q_lower and ("customer" in q_lower or "spend" in q_lower or "order" in q_lower):
            return SQLGeneration(
                sql_query="""
                SELECT 
                    c.name AS customer_name,
                    c.plan_tier,
                    c.country,
                    SUM(o.total_amount_usd) AS total_spent_usd,
                    COUNT(o.id) AS total_orders
                FROM customers c
                JOIN orders o ON c.id = o.customer_id
                WHERE o.status = 'completed'
                GROUP BY c.id, c.name, c.plan_tier, c.country
                ORDER BY total_spent_usd DESC
                LIMIT 5;
                """.strip(),
                thought="Join customers with completed orders, aggregate total spend, and rank top 5.",
                assumptions=["Excluding refunded and pending orders."]
            )

        # 3. Unresolved support tickets
        elif "ticket" in q_lower or "support" in q_lower:
            return SQLGeneration(
                sql_query="""
                SELECT 
                    c.name AS customer_name,
                    c.plan_tier,
                    COUNT(t.id) AS open_tickets_count
                FROM customers c
                JOIN support_tickets t ON c.id = t.customer_id
                WHERE t.status IN ('open', 'in_progress')
                GROUP BY c.id, c.name, c.plan_tier
                HAVING COUNT(t.id) >= 1
                ORDER BY open_tickets_count DESC;
                """.strip(),
                thought="Find customers with support tickets in 'open' or 'in_progress' status.",
                assumptions=["Unresolved tickets defined as status in ('open', 'in_progress')."]
            )

        # 4. Customer count by country
        elif "country" in q_lower:
            return SQLGeneration(
                sql_query="""
                SELECT 
                    country,
                    COUNT(*) AS customer_count
                FROM customers
                GROUP BY country
                ORDER BY customer_count DESC;
                """.strip(),
                thought="Aggregate total customer count grouped by country.",
                assumptions=[]
            )

        # 5. Intentional test failure for self-healing demo
        elif "simulate_error" in q_lower:
            return SQLGeneration(
                sql_query="SELECT invalid_column_name FROM customers LIMIT 1;",
                thought="Intentionally querying a non-existent column to trigger self-healing repair loop.",
                assumptions=[]
            )

        # Generic fallback query
        return SQLGeneration(
            sql_query="SELECT id, name, email, plan_tier, signup_date FROM customers LIMIT 5;",
            thought="Displaying first 5 customers as general overview.",
            assumptions=[]
        )

    def repair_sql(
        self,
        query: str,
        failed_sql: str,
        error_message: str,
        schema_context: str
    ) -> Tuple[str, str]:
        if "invalid_column_name" in failed_sql:
            return (
                "SELECT id, name, email FROM customers LIMIT 1;",
                "Self-Healed: Replaced non-existent 'invalid_column_name' with valid schema columns (id, name, email)."
            )
        # Default repair fallback
        return (
            "SELECT * FROM customers LIMIT 5;",
            "Self-Healed: Replaced erroneous query with standard valid select statement."
        )

    def generate_business_summary(self, query: str, sql: str, result: QueryResult) -> str:
        if not result.rows:
            return "The query executed successfully but returned 0 matching records."

        if "mrr_usd" in result.columns:
            total_mrr = sum(r[result.columns.index("mrr_usd")] for r in result.rows)
            return (
                f"Total monthly recurring revenue (MRR) across all active plans is **${total_mrr:,.2f} USD**. "
                f"The highest revenue plan is **{result.rows[0][0]}** contributing **${result.rows[0][2]:,.2f} USD**."
            )
        elif "total_spent_usd" in result.columns:
            top_cust = result.rows[0][0]
            top_amt = result.rows[0][3]
            return f"Top spending customer is **{top_cust}** with total completed spend of **${top_amt:,.2f} USD**."

        return f"Successfully retrieved {result.row_count} records from the database matching your criteria."
