from typing import TypedDict, Optional


class PipelineState(TypedDict):
    weather_data: Optional[dict]
    analysis: Optional[dict]
    context_docs: Optional[list]
    report: Optional[str]
    errors: list
    status: str
