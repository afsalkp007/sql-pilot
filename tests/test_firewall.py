from sql_pilot.firewall import validate_sql_safety


def test_firewall_allows_safe_select():
    safe_queries = [
        "SELECT * FROM customers;",
        "SELECT id, name FROM customers WHERE is_active = 1;",
        "WITH active_cust AS (SELECT id FROM customers) SELECT * FROM active_cust;",
        "SELECT COUNT(*), plan_tier FROM customers GROUP BY plan_tier ORDER BY 1 DESC"
    ]
    for q in safe_queries:
        is_safe, reason = validate_sql_safety(q)
        assert is_safe, f"Expected '{q}' to be safe, but got: {reason}"
        assert reason is None


def test_firewall_blocks_destructive_mutations():
    malicious_queries = [
        ("DROP TABLE customers;", "DROP"),
        ("DELETE FROM customers WHERE id = 1;", "DELETE"),
        ("UPDATE customers SET plan_tier = 'Free';", "UPDATE"),
        ("INSERT INTO customers (name) VALUES ('Hacker');", "INSERT"),
        ("ALTER TABLE customers ADD COLUMN is_admin INTEGER;", "ALTER"),
        ("TRUNCATE TABLE customers;", "TRUNCATE")
    ]
    for q, keyword in malicious_queries:
        is_safe, reason = validate_sql_safety(q)
        assert not is_safe, f"Expected '{q}' to be blocked"
        assert keyword in reason


def test_firewall_blocks_semicolon_injection():
    injections = [
        "SELECT * FROM customers; DROP TABLE orders;",
        "SELECT 1; DELETE FROM subscriptions;"
    ]
    for q in injections:
        is_safe, reason = validate_sql_safety(q)
        assert not is_safe
        assert "semicolon" in reason.lower()
