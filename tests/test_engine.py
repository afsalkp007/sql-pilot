from sql_pilot.engine import SQLPilotEngine
from sql_pilot.providers import MockSQLProvider


def test_engine_mrr_query():
    engine = SQLPilotEngine(provider=MockSQLProvider())
    resp = engine.run("What is our monthly recurring revenue (MRR) by plan tier?")

    assert not resp.is_blocked_by_guardrail
    assert resp.result is not None
    assert resp.result.row_count > 0
    assert "mrr_usd" in resp.final_sql
    assert "6,000" in resp.business_summary or "Enterprise" in resp.business_summary


def test_engine_self_healing_repair_loop():
    engine = SQLPilotEngine(provider=MockSQLProvider(), max_repair_retries=2)
    # simulate_error triggers an initial failed query with invalid_column_name
    resp = engine.run("simulate_error: show customer data")

    assert not resp.is_blocked_by_guardrail
    assert len(resp.repairs) == 1
    assert resp.repairs[0].attempt_number == 1
    assert "invalid_column_name" in resp.repairs[0].failed_sql
    assert "Self-Healed" in resp.repairs[0].fix_explanation
    assert resp.result is not None
    assert resp.result.row_count == 1


def test_engine_firewall_blocks_destructive_query():
    class MaliciousProvider(MockSQLProvider):
        def generate_sql(self, query, schema_context):
            from sql_pilot.models import SQLGeneration
            return SQLGeneration(
                sql_query="DROP TABLE customers;",
                thought="Attempting to drop table.",
                assumptions=[]
            )

    engine = SQLPilotEngine(provider=MaliciousProvider())
    resp = engine.run("Delete all customer records")

    assert resp.is_blocked_by_guardrail
    assert resp.result is None
    assert "DROP" in resp.guardrail_reason
    assert "Blocked" in resp.business_summary
