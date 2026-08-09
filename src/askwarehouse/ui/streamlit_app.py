"""Streamlit demo UI. Run with:
    streamlit run src/askwarehouse/ui/streamlit_app.py
Chat-style interface: NL answer, chart, the exact SQL that ran, row count,
runtime, sanity findings, and a "Verify this" button that re-runs a
paraphrased, independently-generated query and flags disagreement. Sidebar
exposes the pipeline ablation toggles directly, so a reviewer can turn off
schema retrieval / the repair loop / etc. and watch behavior change live.
"""
import base64

import streamlit as st

from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.chart import render_chart
from askwarehouse.core.nl_answer import generate_nl_answer
from askwarehouse.core.pipeline_config import PipelineConfig
from askwarehouse.core.verify import verify
from askwarehouse.execution.audit import AuditLogger
from askwarehouse.providers.registry import get_provider

st.set_page_config(page_title="AskWarehouse", page_icon="🗄️", layout="wide")


@st.cache_resource(show_spinner="Loading model and building schema/value indexes (first run only)...")
def load_agent(use_schema_retrieval, use_value_index, use_self_critique, use_repair_loop,
                use_semantic_layer, use_cache, use_ambiguity_check):
    provider = get_provider()
    pc = PipelineConfig(
        use_schema_retrieval=use_schema_retrieval, use_value_index=use_value_index,
        use_self_critique=use_self_critique, use_repair_loop=use_repair_loop,
        use_semantic_layer=use_semantic_layer, use_cache=use_cache,
        use_ambiguity_check=use_ambiguity_check,
    )
    return AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=pc)


with st.sidebar:
    st.header("Pipeline configuration")
    st.caption("Toggle stages live -- this is the exact ablation matrix used in the eval table.")
    use_schema_retrieval = st.checkbox("Schema retrieval", value=True)
    use_value_index = st.checkbox("Value index", value=True)
    use_self_critique = st.checkbox("Self-critique pass", value=True)
    use_repair_loop = st.checkbox("Repair loop", value=True)
    use_semantic_layer = st.checkbox("Semantic layer", value=True)
    use_cache = st.checkbox("Fingerprint cache", value=True)
    use_ambiguity_check = st.checkbox("Ambiguity check", value=True)

    st.divider()
    st.header("Safety")
    st.caption(
        "Execution connection is opened `read_only=True` at the DuckDB storage "
        "engine -- not a prompt instruction. Every statement (including "
        "rejections) is written to the audit log regardless of what's shown here."
    )

    if st.checkbox("Show recent audit log"):
        audit = AuditLogger()
        st.dataframe(audit.recent(15), use_container_width=True)

agent = load_agent(use_schema_retrieval, use_value_index, use_self_critique, use_repair_loop,
                    use_semantic_layer, use_cache, use_ambiguity_check)

st.title("🗄️ AskWarehouse")
st.caption("Text-to-SQL analytics agent with execution-verified answers")

if "history" not in st.session_state:
    st.session_state.history = []


def render_entry(idx: int, entry: dict):
    resp = entry["resp"]

    if resp.status == "clarification_needed":
        st.warning(f"**This question is ambiguous.** {resp.ambiguity.reason}")
        st.info(resp.clarifying_question)
        return

    if resp.status == "failed":
        st.error(f"Failed after {len(resp.attempts)} attempt(s).")
        with st.expander("Attempts"):
            for a in resp.attempts:
                st.write(f"attempt {a.attempt_number} [{a.stage}/{a.outcome}]: {a.error}")
        st.code(resp.sql, language="sql")
        return

    st.write(entry["answer"])

    chart = entry["chart"]
    if chart.png_base64:
        st.image(base64.b64decode(chart.png_base64))
    elif chart.kind == "single_value":
        st.metric(resp.result.columns[0], resp.result.rows[0][0])
    else:
        st.dataframe(resp.result.rows, use_container_width=True)

    cols = st.columns(4)
    cols[0].metric("Rows", resp.result.row_count)
    cols[1].metric("Query latency", f"{resp.result.latency_ms:.0f} ms")
    cols[2].metric("Total latency", f"{resp.total_latency_ms:.0f} ms")
    cols[3].metric("LLM calls", resp.llm_calls)

    for f in resp.sanity_findings:
        (st.warning if f.severity == "warning" else st.info)(f"**{f.code}**: {f.message}")

    with st.expander("SQL + trace"):
        badge = "cache hit" if resp.cache_hit else f"{len(resp.attempts)} attempt(s)"
        st.caption(badge)
        st.code(resp.sql, language="sql")
        if resp.plan_text:
            st.caption("Plan")
            st.text(resp.plan_text)
        if resp.value_hints:
            st.caption("Value hints")
            st.text(resp.value_hints)

    if st.button("Verify this", key=f"verify_{idx}"):
        with st.spinner("Re-running with an independently-generated, paraphrased question..."):
            v = verify(agent, entry["question"], resp.sql, resp.result.columns, resp.result.rows)
        entry["verify"] = v

    if entry.get("verify"):
        v = entry["verify"]
        if v.match:
            st.success(f"✓ Verified against: \"{v.verify_question}\" -- results agree.")
        else:
            st.error(f"✗ Mismatch against: \"{v.verify_question}\" -- {v.detail}")
        with st.expander("Verification SQL"):
            st.code(v.verify_sql, language="sql")


for i, entry in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        render_entry(i, entry)

question = st.chat_input("Ask a business question about the warehouse...")

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            resp = agent.ask(question)
            entry = {"question": question, "resp": resp}
            if resp.status == "answered":
                entry["answer"] = generate_nl_answer(
                    agent.provider, question, resp.result.columns, resp.result.rows
                )
                entry["chart"] = render_chart(resp.result.columns, resp.result.rows, title=question)
        render_entry(len(st.session_state.history), entry)
        st.session_state.history.append(entry)
