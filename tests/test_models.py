import pytest
from pydantic import ValidationError
from sql_pilot.models import (
    ColumnInfo,
    TableSchema,
    QueryResult,
    SQLPilotResponse
)


def test_column_info_model():
    col = ColumnInfo(name="id", data_type="INTEGER", is_primary_key=True)
    assert col.name == "id"
    assert col.is_primary_key


def test_query_result_model():
    res = QueryResult(
        columns=["name", "mrr"],
        rows=[["Acme", 1500.0]],
        row_count=1,
        execution_time_ms=1.5
    )
    assert res.row_count == 1
    assert res.columns == ["name", "mrr"]


def test_sql_pilot_response_validation():
    with pytest.raises(ValidationError):
        SQLPilotResponse(
            user_query="test",
            final_sql="SELECT 1",
            business_summary="summary",
            total_latency_ms=-5.0  # Invalid: latency must be >= 0.0
        )
