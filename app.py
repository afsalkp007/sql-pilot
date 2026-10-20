"""
SQLPilot - Interactive Data Cockpit (Streamlit).
Allows users to explore the database schema, query in plain English,
inspect generated SQL, view self-healing repairs, and visualize tables.
"""

import streamlit as st
import pandas as pd
from pathlib import Path

from sql_pilot.engine import SQLPilotEngine
from sql_pilot.providers import GeminiSQLProvider, OpenAISQLProvider, MockSQLProvider
from sql_pilot.database import DatabaseManager

st.set_page_config(
    page_title="SQLPilot | Text-to-SQL Explorer",
    page_icon="🧭",
    layout="wide"
)

st.title("🧭 SQLPilot: Autonomous Text-to-SQL Explorer")
st.markdown(
    "Query relational databases in plain English with **read-only safety guardrails**, "
    "**autonomous self-healing query repair**, and executive business summaries."
)

# Sidebar setup
st.sidebar.header("⚙️ Engine Configuration")
provider_choice = st.sidebar.selectbox(
    "LLM Provider",
    ["Mock (Offline Demo)", "Gemini 2.5 Flash", "OpenAI (GPT-4o-mini)"],
    index=0
)

api_key = ""
if "Gemini" in provider_choice:
    api_key = st.sidebar.text_input("Gemini API Key", type="password", help="Get free key at aistudio.google.com")
elif "OpenAI" in provider_choice:
    api_key = st.sidebar.text_input("OpenAI API Key", type="password")

max_retries = st.sidebar.slider("Self-Healing Max Retries", min_value=1, max_value=4, value=2)

# Database Manager
@st.cache_resource
def get_db_manager():
    return DatabaseManager()

db_manager = get_db_manager()
metadata = db_manager.introspect_schema()

# Sidebar Schema Explorer
st.sidebar.divider()
st.sidebar.subheader("🗄️ Database Tables")
for table in metadata.tables:
    with st.sidebar.expander(f"📋 `{table.table_name}` ({len(table.columns)} cols)"):
        col_df = pd.DataFrame([
            {"Column": c.name, "Type": c.data_type, "PK": "✓" if c.is_primary_key else ""}
            for c in table.columns
        ])
        st.dataframe(col_df, hide_index=True, use_container_width=True)

# Sample Questions
st.subheader("💡 Sample Business Questions")
col1, col2, col3, col4, col5 = st.columns(5)

selected_question = None
with col1:
    if st.button("💰 Monthly Recurring Revenue", use_container_width=True):
        selected_question = "What is our monthly recurring revenue (MRR) by plan tier?"
with col2:
    if st.button("👑 Top Spending Customers", use_container_width=True):
        selected_question = "Show the top 5 customers by total completed order amount."
with col3:
    if st.button("🎫 Open Support Tickets", use_container_width=True):
        selected_question = "Which customers have open or in-progress support tickets?"
with col4:
    if st.button("🛡️ Drop Table (Test Firewall)", use_container_width=True):
        selected_question = "DROP TABLE customers;"
with col5:
    if st.button("🛠️ Test Self-Healing Repair", use_container_width=True):
        selected_question = "simulate_error: Query customer data with column typos"

# Input Box
query_input = st.text_input(
    "Enter a question in plain English:",
    value=selected_question or "",
    placeholder="e.g. Which country has the highest customer count?"
)

if st.button("🚀 Run Query", type="primary") or selected_question:
    if not query_input.strip():
        st.warning("Please enter a question first.")
    else:
        # Provider selection
        if "Gemini" in provider_choice and api_key:
            provider = GeminiSQLProvider(api_key=api_key)
        elif "OpenAI" in provider_choice and api_key:
            provider = OpenAISQLProvider(api_key=api_key)
        else:
            provider = MockSQLProvider()

        engine = SQLPilotEngine(
            db_manager=db_manager,
            provider=provider,
            max_repair_retries=max_retries
        )

        with st.spinner("Translating question, validating safety, and executing SQL..."):
            resp = engine.run(query_input)
            st.session_state["sql_resp"] = resp

# Display Response
if "sql_resp" in st.session_state:
    resp = st.session_state["sql_resp"]
    st.divider()

    # Latency and Status KPI
    k1, k2, k3 = st.columns(3)
    k1.metric("Execution Latency", f"{resp.total_latency_ms} ms")
    k2.metric("Rows Returned", resp.result.row_count if resp.result else 0)
    k3.metric("Safety Status", "🚫 BLOCKED" if resp.is_blocked_by_guardrail else "✅ SAFE (Read-Only)")

    # 1. Guardrail Blocked Alert
    if resp.is_blocked_by_guardrail:
        st.error(f"### 🛡️ SQL Safety Firewall Alert\n\n**Violation:** {resp.guardrail_reason}")
        st.code(resp.final_sql, language="sql")
        st.info("💡 **Why was this query blocked?** SQLPilot enforces strict zero-trust read-only governance. Destructive mutations like `DROP`, `DELETE`, `UPDATE`, and `ALTER` are blocked at the firewall layer.")

    else:
        # 2. Self-Healing Alert (if triggered)
        if resp.repairs:
            for rep in resp.repairs:
                st.warning(
                    f"### 🛠️ Self-Healing Query Repair Triggered (Attempt #{rep.attempt_number})\n"
                    f"**Database Error:** `{rep.error_message}`\n\n"
                    f"**Fix Applied:** {rep.fix_explanation}"
                )
                with st.expander("Compare Failed vs Repaired SQL"):
                    st.caption("Failed SQL:")
                    st.code(rep.failed_sql, language="sql")
                    st.caption("Repaired SQL:")
                    st.code(rep.repaired_sql, language="sql")

        # 3. Business Summary
        st.success(f"### 💡 Executive Business Summary\n\n{resp.business_summary}")

        # 4. Executed SQL Code Block
        with st.expander("View Generated SQL Query", expanded=True):
            st.code(resp.final_sql, language="sql")
            if resp.assumptions_made:
                st.caption(f"**Assumptions:** {' • '.join(resp.assumptions_made)}")

        # 5. Dataframe Table View
        if resp.result and resp.result.rows:
            st.subheader(f"📊 Results ({resp.result.row_count} records)")
            df = pd.DataFrame(resp.result.rows, columns=resp.result.columns)
            st.dataframe(df, use_container_width=True)

            # Quick chart visualization if 2 columns (categorical + numerical)
            if len(df.columns) == 2 and pd.api.types.is_numeric_dtype(df.iloc[:, 1]):
                st.bar_chart(df.set_index(df.columns[0]))
