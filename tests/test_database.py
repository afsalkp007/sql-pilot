import sqlite3
import pytest
from sql_pilot.database import DatabaseManager


def test_database_manager_introspection():
    db = DatabaseManager()
    meta = db.introspect_schema()

    assert meta.dialect == "sqlite"
    table_names = [t.table_name for t in meta.tables]
    assert "customers" in table_names
    assert "subscriptions" in table_names
    assert "orders" in table_names
    assert "support_tickets" in table_names

    # Check customers table columns
    cust_table = next(t for t in meta.tables if t.table_name == "customers")
    col_names = [c.name for c in cust_table.columns]
    assert "email" in col_names
    assert "plan_tier" in col_names


def test_database_manager_execution():
    db = DatabaseManager()
    res = db.execute_query("SELECT id, name FROM customers LIMIT 2;")
    assert res.row_count == 2
    assert res.columns == ["id", "name"]
    assert res.execution_time_ms >= 0.0


def test_database_manager_syntax_error():
    db = DatabaseManager()
    with pytest.raises(sqlite3.OperationalError):
        db.execute_query("SELECT nonexistent_col FROM customers;")
