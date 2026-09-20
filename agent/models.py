"""Shared Pydantic contracts for the agent, API, tools, and frontend."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


IntentName = Literal[
    "pattern_search",
    "aggregation",
    "entity_lookup",
    "broad_eda",
]

PatternType = Literal[
    "structuring",
    "smurfing",
    "layering",
    "rapid_cashout",
    "behavioural_change",
    "cycle",
    "fan_in",
    "fan_out",
    "single_large",
    "deposit_send",
    "cash_withdrawal",
    "bipartite",
    "gather_scatter",
    "scatter_gather",
]


class IntentFilters(BaseModel):
    """Filters extracted from the natural-language query."""

    model_config = ConfigDict(extra="forbid")

    date_range: tuple[str, str] | None = None
    entity_id: str | None = None
    from_country: str | None = None
    payment_format: str | None = None
    min_amount: float | None = Field(default=None, ge=0)
    max_amount: float | None = Field(default=None, ge=0)
    min_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_ranges(self) -> "IntentFilters":
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount cannot be greater than max_amount")
        if self.date_range is not None:
            try:
                start = date.fromisoformat(self.date_range[0])
                end = date.fromisoformat(self.date_range[1])
            except ValueError as exc:
                raise ValueError("date_range values must use ISO YYYY-MM-DD") from exc
            if start > end:
                raise ValueError("date_range start cannot be after its end")
        return self


class IntentResult(BaseModel):
    """Validated output from intent extraction."""

    model_config = ConfigDict(extra="forbid")

    intent: IntentName
    pattern_type: PatternType | None = None
    filters: IntentFilters = Field(default_factory=IntentFilters)
    entities: list[str] = Field(default_factory=list)
    require_ml: bool = False
    require_graph: bool = False
    require_eda: bool = False


class SkippedTool(BaseModel):
    """A tool omitted from a plan and the policy reason for omitting it."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    reason: str


class PlanResult(BaseModel):
    """Ordered tool plan produced by the dynamic planner."""

    model_config = ConfigDict(extra="forbid")

    steps: list[str]
    skipped: list[SkippedTool] = Field(default_factory=list)
    reasoning: str


class ExecutionStep(BaseModel):
    """One run/skip entry in the observable execution trace."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    status: Literal["run", "skipped"]
    duration_ms: float = Field(default=0.0, ge=0)
    reason: str


class AggregationRow(BaseModel):
    """One ranked group returned by a threshold aggregation query."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    txn_count: int = Field(ge=0)
    total_amount: float = Field(ge=0)
    avg_amount: float = Field(ge=0)
    min_amount: float = Field(ge=0)
    max_amount: float = Field(ge=0)
    date_first: str
    date_last: str
    distinct_counterparties: int = Field(ge=0)
    risk_score: float = Field(default=0.0, ge=0, le=1)
    risk_label: Literal["low", "medium", "high"] = "low"


class AggregationResult(BaseModel):
    """Structured response for direct grouped/count threshold questions."""

    model_config = ConfigDict(extra="forbid")

    rows: list[AggregationRow] = Field(default_factory=list)
    total_groups: int = Field(default=0, ge=0)
    filter_applied: dict[str, Any] = Field(default_factory=dict)
    group_by_field: str


class TransactionEvidence(BaseModel):
    """A transaction supporting an entity-level risk decision."""

    model_config = ConfigDict(extra="forbid")

    txn_id: str
    timestamp: str
    amount: float = Field(ge=0)
    payment_format: str = ""
    to_account: str = ""
    from_country: str | None = None
    to_country: str | None = None
    triggered_rules: list[str] = Field(default_factory=list)


class RiskContribution(BaseModel):
    """Fully reconcilable detector-level risk score breakdown."""

    model_config = ConfigDict(extra="forbid")

    rule_score: float = Field(ge=0, le=1)
    rule_weight: float = Field(ge=0, le=1)
    rule_contribution: float = Field(ge=0, le=1)
    stat_score: float = Field(ge=0, le=1)
    stat_weight: float = Field(ge=0, le=1)
    stat_contribution: float = Field(ge=0, le=1)
    ml_score: float = Field(ge=0, le=1)
    ml_weight: float = Field(ge=0, le=1)
    ml_contribution: float = Field(ge=0, le=1)
    country_boost: float = Field(ge=0, le=1)
    active_detector_count: int = Field(ge=0)
    final_risk_score: float = Field(ge=0, le=1)
    formula: str


class FlaggedEntity(BaseModel):
    """Stable response contract for a suspicious entity."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_label: Literal["low", "medium", "high"]
    escalation_action: Literal["monitor", "flag_for_review", "report"]
    rule_flags: list[str] = Field(default_factory=list)
    rule_score: float = Field(default=0.0, ge=0, le=1)
    stat_score: float = Field(default=0.0, ge=0, le=1)
    ml_score: float = Field(default=0.0, ge=0, le=1)
    saml_d_typology: str = ""
    explanation: str = ""
    sar_draft: str = ""
    citation: str = ""
    risk_contributions: RiskContribution | None = None
    top_transactions: list[TransactionEvidence] = Field(default_factory=list)
    txn_count: int = Field(default=0, ge=0)
    total_amount: float = Field(default=0.0, ge=0)
    observation_window: tuple[str, str] | None = None
    distinct_counterparties: int = Field(default=0, ge=0)


class SummaryStats(BaseModel):
    """Query-slice summary returned with every agent response."""

    model_config = ConfigDict(extra="forbid")

    total_analyzed: int = Field(default=0, ge=0)
    flagged: int = Field(default=0, ge=0)
    high_risk: int = Field(default=0, ge=0)


class AgentResponse(BaseModel):
    """Complete structured response returned by ``AgentRunner`` and FastAPI."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str | None = None
    dataset_id: str | None = None
    dataset_name: str | None = None
    query: str
    intent: IntentResult
    plan: PlanResult
    execution_trace: list[ExecutionStep]
    top_entities: list[FlaggedEntity] = Field(default_factory=list)
    summary_stats: SummaryStats = Field(default_factory=SummaryStats)
    eda_summary: dict[str, Any] | None = None
    charts: list[dict[str, Any]] | None = None
    graph: dict[str, Any] | None = None
    aggregation: AggregationResult | None = None


class QueryRequest(BaseModel):
    """FastAPI request body for ``POST /query``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    dataset_id: str | None = Field(default=None, max_length=80)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("query cannot be blank")
        return normalized

    @field_validator("dataset_id")
    @classmethod
    def normalize_dataset_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("dataset_id cannot be blank")
        return normalized


class InvestigationRecord(BaseModel):
    """Persisted investigation metadata returned by the workflow API."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    query: str
    intent: str
    pattern_type: str | None = None
    status: Literal["open", "in_review", "escalated", "closed"]
    disposition: (
        Literal[
            "pending",
            "true_positive",
            "false_positive",
            "escalated",
            "sar_filed",
        ]
        | None
    ) = "pending"
    flagged_count: int = Field(default=0, ge=0)
    high_risk_count: int = Field(default=0, ge=0)
    alert_count: int = Field(default=0, ge=0)
    response: AgentResponse
    created_at: str
    updated_at: str


class InvestigationSummary(BaseModel):
    """Compact investigation list item; detail is loaded on demand."""

    model_config = ConfigDict(extra="forbid")

    investigation_id: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    query: str
    intent: str
    pattern_type: str | None = None
    status: Literal["open", "in_review", "escalated", "closed"]
    disposition: str | None = None
    flagged_count: int = Field(default=0, ge=0)
    high_risk_count: int = Field(default=0, ge=0)
    alert_count: int = Field(default=0, ge=0)
    created_at: str
    updated_at: str


class AlertQueueItem(BaseModel):
    """One persistent alert in the analyst review queue."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str
    dataset_id: str | None = None
    entity_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_label: Literal["low", "medium", "high"]
    escalation_action: Literal["monitor", "flag_for_review", "report"]
    saml_d_typology: str = ""
    created_at: str
    sla_hours: int = Field(ge=1)
    age_hours: float = Field(ge=0)
    assigned_to: str | None = None
    status: Literal["new", "in_review", "escalated", "closed"]
    disposition: (
        Literal[
            "pending",
            "true_positive",
            "false_positive",
            "escalated",
            "sar_filed",
        ]
        | None
    ) = "pending"
    investigation_id: str
    notes: str = ""


class QueueAssignmentRequest(BaseModel):
    """Analyst assignment request for one queue item."""

    model_config = ConfigDict(extra="forbid")

    assigned_to: str = Field(min_length=1, max_length=120)
    actor: str = Field(default="demo.analyst", min_length=1, max_length=120)


class QueueDispositionRequest(BaseModel):
    """Controlled disposition transition for one queue item."""

    model_config = ConfigDict(extra="forbid")

    disposition: Literal[
        "true_positive",
        "false_positive",
        "escalated",
    ]
    actor: str = Field(default="demo.analyst", min_length=1, max_length=120)


class QueueNoteRequest(BaseModel):
    """Append-only analyst note request."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=4_000)
    actor: str = Field(default="demo.analyst", min_length=1, max_length=120)


class AuditEvent(BaseModel):
    """Immutable system or analyst activity retained for examination."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    event_id: str
    dataset_id: str | None = None
    event_type: str
    actor: str
    investigation_id: str | None = None
    alert_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    risk_policy_version: str
    model_version: str
    dataset_snapshot: str
    created_at: str


class CustomerSummary(BaseModel):
    """Aggregated customer/account activity with current workflow risk."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    primary_bank: str
    outbound_count: int = Field(ge=0)
    inbound_count: int = Field(ge=0)
    total_sent: float = Field(ge=0)
    total_received: float = Field(ge=0)
    max_transaction: float = Field(ge=0)
    distinct_counterparties: int = Field(ge=0)
    first_seen: str
    last_seen: str
    alert_count: int = Field(ge=0)
    open_alert_count: int = Field(ge=0)
    max_risk_score: float | None = Field(default=None, ge=0, le=1)
    risk_label: Literal["unscored", "low", "medium", "high"]


class CounterpartySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    transaction_count: int = Field(ge=0)
    total_amount: float = Field(ge=0)
    direction: Literal["inbound", "outbound"]


class CustomerDetail(BaseModel):
    """One customer profile with counterparties, payment mix, and alerts."""

    model_config = ConfigDict(extra="forbid")

    summary: CustomerSummary
    payment_formats: dict[str, int] = Field(default_factory=dict)
    currencies: list[str] = Field(default_factory=list)
    known_laundering_transactions: int = Field(default=0, ge=0)
    top_counterparties: list[CounterpartySummary] = Field(default_factory=list)
    alerts: list[AlertQueueItem] = Field(default_factory=list)


class TransactionRecord(BaseModel):
    """Stable evidence-browser representation of one transaction."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    timestamp: str
    from_bank: str
    from_account: str
    to_bank: str
    to_account: str
    amount_paid: float = Field(ge=0)
    amount_received: float = Field(ge=0)
    paying_currency: str
    receiving_currency: str
    payment_format: str
    is_laundering: bool


class DatasetInfo(BaseModel):
    """Governed metadata for one isolated analytical dataset."""

    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    display_name: str
    source_file: str | None = None
    dataset_type: Literal["primary", "knowledge", "kyc"]
    file_size_bytes: int = Field(default=0, ge=0)
    row_count: int = Field(default=0, ge=0)
    laundering_count: int = Field(default=0, ge=0)
    laundering_rate: float = Field(default=0.0, ge=0, le=1)
    date_min: str | None = None
    date_max: str | None = None
    schema_version: str = "1.0"
    md5_fingerprint: str | None = None
    ingested_at: str
    is_active: bool = False
    notes: str = ""
    column_map: dict[str, str] = Field(default_factory=dict)
    schema_detected: str = ""


class DatasetUploadResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    display_name: str
    row_count: int = Field(ge=0)
    schema_detected: str
    warnings: list[str] = Field(default_factory=list)
    eda_summary: dict[str, Any] = Field(default_factory=dict)


class DatasetSwitchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_dataset_id: str | None = None
    active_dataset_id: str
    row_count: int = Field(ge=0)
    message: str


class HealthResponse(BaseModel):
    """Dependency-free liveness contract for orchestration probes."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str
    timestamp: str


class ReadinessCheck(BaseModel):
    """Readiness state for one governed runtime dependency."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    detail: str


class ReadinessResponse(BaseModel):
    """Operational readiness contract with inspectable dependency evidence."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ready", "not_ready"]
    service: str
    version: str
    timestamp: str
    checks: dict[str, ReadinessCheck]


class SchemaCatalogResponse(BaseModel):
    """Published request and response JSON-schema catalog."""

    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    schemas: dict[str, dict[str, Any]]
