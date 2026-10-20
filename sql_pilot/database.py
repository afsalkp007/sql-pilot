"""
Database introspection, query execution, and sample database seeding.
Provides read-only database connections and schema extraction for prompt grounding.
"""

import sqlite3
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from .models import DatabaseMetadata, TableSchema, ColumnInfo, QueryResult


def get_default_db_path() -> Path:
    """Return default path to sample database."""
    return Path(__file__).resolve().parent.parent / "ecommerce_saas.db"


class DatabaseManager:
    """Manages database connection, schema introspection, and safe execution."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else get_default_db_path()
        if not self.db_path.exists():
            self.seed_sample_database()

    def get_connection(self) -> sqlite3.Connection:
        """Create a connection with read-only PRAGMA protection where possible."""
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_writable_connection(self) -> sqlite3.Connection:
        """Used strictly during initial seeding."""
        return sqlite3.connect(self.db_path)

    def introspect_schema(self) -> DatabaseMetadata:
        """Introspect tables, columns, foreign keys, and preview rows."""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Get all user tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        table_names = [row[0] for row in cursor.fetchall()]

        tables: List[TableSchema] = []

        for tname in table_names:
            # Columns
            cursor.execute(f"PRAGMA table_info({tname});")
            col_rows = cursor.fetchall()
            columns = [
                ColumnInfo(
                    name=col["name"],
                    data_type=col["type"] or "TEXT",
                    is_primary_key=bool(col["pk"]),
                    nullable=not bool(col["notnull"])
                )
                for col in col_rows
            ]

            # Foreign Keys
            cursor.execute(f"PRAGMA foreign_key_list({tname});")
            fk_rows = cursor.fetchall()
            foreign_keys = [
                {
                    "from_column": fk["from"],
                    "to_table": fk["table"],
                    "to_column": fk["to"]
                }
                for fk in fk_rows
            ]

            # Sample Rows
            cursor.execute(f"SELECT * FROM {tname} LIMIT 3;")
            sample_data = [dict(row) for row in cursor.fetchall()]

            tables.append(TableSchema(
                table_name=tname,
                columns=columns,
                foreign_keys=foreign_keys,
                sample_rows=sample_data
            ))

        conn.close()
        return DatabaseMetadata(dialect="sqlite", tables=tables)

    def execute_query(self, sql: str) -> QueryResult:
        """Execute query safely and return QueryResult."""
        start_time = time.perf_counter()
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchall()
            rows = [list(r) for r in raw_rows]
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                execution_time_ms=elapsed_ms
            )
        finally:
            conn.close()

    def format_schema_for_prompt(self) -> str:
        """Generate concise markdown documentation of the schema for the LLM."""
        meta = self.introspect_schema()
        lines = []
        for t in meta.tables:
            col_desc = ", ".join([f"{c.name} ({c.data_type})" for c in t.columns])
            lines.append(f"Table `{t.table_name}`: [{col_desc}]")
            if t.foreign_keys:
                fks = [f"{fk['from_column']} -> {fk['to_table']}.{fk['to_column']}" for fk in t.foreign_keys]
                lines.append(f"  Foreign Keys: {', '.join(fks)}")
            if t.sample_rows:
                lines.append(f"  Sample Row: {t.sample_rows[0]}")
            lines.append("")
        return "\n".join(lines)

    def seed_sample_database(self) -> None:
        """Populate realistic e-commerce and SaaS data."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.get_writable_connection()
        cursor = conn.cursor()

        cursor.executescript("""
        DROP TABLE IF EXISTS support_tickets;
        DROP TABLE IF EXISTS orders;
        DROP TABLE IF EXISTS subscriptions;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            plan_tier TEXT NOT NULL CHECK(plan_tier IN ('Free', 'Starter', 'Pro', 'Enterprise')),
            signup_date TEXT NOT NULL,
            country TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            plan_name TEXT NOT NULL,
            monthly_price_usd REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'past_due', 'canceled')),
            start_date TEXT NOT NULL,
            renewal_date TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            total_amount_usd REAL NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('completed', 'refunded', 'pending')),
            payment_method TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            priority TEXT NOT NULL CHECK(priority IN ('P0', 'P1', 'P2', 'P3')),
            status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'in_progress')),
            created_at TEXT NOT NULL,
            resolution_time_hours REAL,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        -- Seed Customers
        INSERT INTO customers (name, email, plan_tier, signup_date, country, is_active) VALUES
        ('Acme Corp', 'billing@acme.com', 'Enterprise', '2026-01-15', 'USA', 1),
        ('TechNova Solutions', 'finance@technova.io', 'Pro', '2026-02-10', 'Germany', 1),
        ('CloudScale Labs', 'ops@cloudscale.net', 'Enterprise', '2026-03-01', 'UK', 1),
        ('BetaGrowth Ltd', 'sarah@betagrowth.co', 'Starter', '2026-03-12', 'USA', 1),
        ('SwiftRetail Inc', 'alex@swiftretail.com', 'Pro', '2026-04-05', 'Canada', 1),
        ('SoloDev Studio', 'mark@solodev.org', 'Free', '2026-05-20', 'France', 0),
        ('HyperData AI', 'admin@hyperdata.ai', 'Enterprise', '2026-06-18', 'USA', 1),
        ('Nexus Health', 'lead@nexushealth.com', 'Starter', '2026-07-02', 'UK', 1);

        -- Seed Subscriptions
        INSERT INTO subscriptions (customer_id, plan_name, monthly_price_usd, status, start_date, renewal_date) VALUES
        (1, 'Enterprise Plan', 1500.0, 'active', '2026-01-15', '2026-11-15'),
        (2, 'Pro Plan', 250.0, 'active', '2026-02-10', '2026-11-10'),
        (3, 'Enterprise Plan', 2200.0, 'active', '2026-03-01', '2026-11-01'),
        (4, 'Starter Plan', 49.0, 'past_due', '2026-03-12', '2026-10-12'),
        (5, 'Pro Plan', 250.0, 'active', '2026-04-05', '2026-11-05'),
        (7, 'Enterprise Plan', 1800.0, 'active', '2026-06-18', '2026-11-18'),
        (8, 'Starter Plan', 49.0, 'canceled', '2026-07-02', '2026-09-02');

        -- Seed Orders
        INSERT INTO orders (customer_id, order_date, total_amount_usd, status, payment_method) VALUES
        (1, '2026-01-15', 1500.0, 'completed', 'invoice'),
        (1, '2026-06-15', 5000.0, 'completed', 'wire_transfer'),
        (2, '2026-02-10', 250.0, 'completed', 'credit_card'),
        (3, '2026-03-01', 2200.0, 'completed', 'wire_transfer'),
        (3, '2026-08-14', 12000.0, 'completed', 'wire_transfer'),
        (4, '2026-03-12', 49.0, 'completed', 'credit_card'),
        (5, '2026-04-05', 250.0, 'completed', 'credit_card'),
        (7, '2026-06-18', 1800.0, 'completed', 'wire_transfer'),
        (5, '2026-07-20', 120.0, 'refunded', 'credit_card');

        -- Seed Support Tickets
        INSERT INTO support_tickets (customer_id, priority, status, created_at, resolution_time_hours) VALUES
        (1, 'P0', 'resolved', '2026-02-01', 1.5),
        (3, 'P1', 'resolved', '2026-03-15', 4.0),
        (4, 'P2', 'open', '2026-10-15', NULL),
        (4, 'P2', 'open', '2026-10-18', NULL),
        (4, 'P3', 'open', '2026-10-19', NULL),
        (2, 'P2', 'resolved', '2026-05-10', 6.2),
        (7, 'P1', 'in_progress', '2026-10-17', NULL);
        """)

        conn.commit()
        conn.close()
