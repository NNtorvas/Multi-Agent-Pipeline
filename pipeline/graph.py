import logging

from langgraph.graph import StateGraph, END

from agents.data_agent import run_data_agent
from agents.analysis_agent import run_analysis_agent
from agents.context_agent import run_context_agent
from agents.report_agent import run_report_agent
from pipeline.state import PipelineState


def build_pipeline():
    """
    Compile the four-node sequential LangGraph state machine.

    Explicit edges enforce the data → analysis → context → report ordering.
    Each node receives the full PipelineState and returns only the keys it mutates;
    LangGraph merges the returned dict back into the shared state.
    """
    graph = StateGraph(PipelineState)

    graph.add_node("data", run_data_agent)
    graph.add_node("analysis", run_analysis_agent)
    graph.add_node("context", run_context_agent)
    graph.add_node("report", run_report_agent)

    graph.set_entry_point("data")
    graph.add_edge("data", "analysis")
    graph.add_edge("analysis", "context")
    graph.add_edge("context", "report")
    graph.add_edge("report", END)

    return graph.compile()


def run_pipeline() -> PipelineState:
    pipeline = build_pipeline()
    initial: PipelineState = {
        "weather_data": None,
        "analysis": None,
        "context_docs": None,
        "report": None,
        "errors": [],
        "status": "started",
    }
    logging.info("[pipeline] Invoking LangGraph state machine")
    result: PipelineState = pipeline.invoke(initial)
    logging.info(
        "[pipeline] Finished with status=%s errors=%s",
        result["status"],
        result["errors"],
    )
    return result
