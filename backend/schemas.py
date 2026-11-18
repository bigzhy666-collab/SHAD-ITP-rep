from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Keep explicit: different artifacts may need a different adapter in future.
FIELDS = (
    "outdoor_temperature", "p_net_supply_temperature", "p_net_return_temperature",
    "p_net_meter_heat_power", "p_net_meter_flow", "p_hc1_return_temperature",
    "s_hc1_supply_temperature", "s_hc1_supply_temperature_setpoint",
)
UNITS = {field: ("kW" if field.endswith("heat_power") else
                 "L/h" if field.endswith("flow") else "degC") for field in FIELDS}
OPTIONAL_FIELDS = (
    "p_hc1_return_temperature_setpoint", "s_dhw_supply_temperature",
    "s_dhw_supply_temperature_setpoint", "s_dhw_upper_storage_temperature",
    "s_dhw_lower_storage_temperature", "s_dhw_upper_storage_temperature_setpoint",
)
ALL_FIELDS = (*FIELDS, *OPTIONAL_FIELDS)
ALL_UNITS = {**UNITS, **dict.fromkeys(OPTIONAL_FIELDS, "degC")}
PREPROCESSING_VERSION = "normalized-30min-blocks-v2"
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")]
FiniteNumber = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Station(StrictModel):
    id: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    code: Identifier
    enterpriseId: Identifier
    networkId: Identifier
    segmentId: Identifier
    timezone: str

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("必须使用有效的 IANA 时区") from exc
        return value


class ModelRegistration(StrictModel):
    id: Identifier
    version: Identifier
    stationId: Identifier
    name: Annotated[str, Field(min_length=1, max_length=200)]
    artifact: str
    artifactChecksum: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    trainingTimezone: str
    isDemo: bool
    description: str = ""

    _timezone_exists = field_validator("trainingTimezone")(Station.timezone_exists.__func__)


class RegistryConfig(StrictModel):
    stations: list[Station] = Field(default_factory=list)
    models: list[ModelRegistration] = Field(default_factory=list)
    organizations: dict[str, list[dict]] = Field(default_factory=dict)


class StationCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    code: Identifier
    enterpriseId: Identifier
    networkId: Identifier
    segmentId: Identifier
    timezone: str

    _timezone_exists = field_validator("timezone")(Station.timezone_exists.__func__)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("名称不能为空")
        return value.strip()


class OrganizationCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    code: Identifier
    enterpriseId: Identifier | None = None
    networkId: Identifier | None = None

    _nonblank = field_validator("name")(StationCreate.nonblank.__func__)


class OrganizationUpdate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    code: Identifier
    active: bool
    expectedRevision: Annotated[int, Field(ge=1)]

    _nonblank = field_validator("name")(StationCreate.nonblank.__func__)


class ImportManifest(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    stationId: Identifier
    timezone: str
    encoding: Literal["utf-8", "utf-8-sig"]
    delimiter: Literal[",", ";"]
    timeColumn: Annotated[str, Field(min_length=1, max_length=200)]
    columnMapping: dict[str, str]
    sourceUnits: dict[str, str]

    _nonblank = field_validator("name")(StationCreate.nonblank.__func__)


class InputSample(StrictModel):
    timestamp: Annotated[str, Field(min_length=1, max_length=60)]
    values: dict[str, FiniteNumber | None]


class DetectionContext(StrictModel):
    enterpriseId: Identifier
    networkId: Identifier
    segmentId: Identifier
    stationId: Identifier


class DetectionRange(StrictModel):
    start: Annotated[str, Field(min_length=1, max_length=60)]
    end: Annotated[str, Field(min_length=1, max_length=60)]


class DetectionCreate(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    context: DetectionContext
    datasetId: Identifier
    modelId: Identifier
    modelVersion: Identifier
    range: DetectionRange

    _nonblank = field_validator("name")(StationCreate.nonblank.__func__)


class EmptyRequest(StrictModel):
    pass


class ReportCreate(StrictModel):
    detectionId: Identifier
    eventIds: Annotated[list[Identifier], Field(min_length=1, max_length=5000)]
    diagnosisId: Identifier | None

    @field_validator('eventIds')
    @classmethod
    def unique_events(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('事件不得重复')
        return sorted(value)


class ReportRevision(StrictModel):
    expectedRevision: Annotated[int, Field(ge=1)]


class ReportNote(ReportRevision):
    note: Annotated[str, Field(max_length=2000)]


class InferenceInput(StrictModel):
    """Low-level integration endpoint; not a persisted frontend detection task."""
    stationId: Identifier
    modelId: Identifier
    modelVersion: Identifier
    timezone: Annotated[str, Field(min_length=1, max_length=100)]
    units: dict[str, str]
    samples: Annotated[list[InputSample], Field(min_length=1, max_length=5000)]


class ScorePoint(StrictModel):
    timestamp: str
    blockId: str
    score: FiniteNumber
    threshold: FiniteNumber
    alarm: bool
    criticality: Annotated[int, Field(ge=0)]
    health: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    confirmed: bool


class ConfirmedSegment(StrictModel):
    blockId: str
    kind: Literal["station_state_anomaly"]
    title: str
    start: str
    end: str
    hours: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    peak_score: FiniteNumber
    max_criticality: Annotated[int, Field(ge=0)]
    affectedMetrics: list[str] | None
    cause: None
    solution: None
    boundary: Literal["within_range", "touches_range_start", "touches_range_end", "touches_both"]


class InferenceSummary(StrictModel):
    pointCount: int
    alarmPointCount: int
    confirmedPointCount: int
    eventCount: int
    blockCount: int
    qualityIssueCount: int


class InferenceOutput(StrictModel):
    stationId: str
    modelSnapshot: dict
    preprocessingVersion: str
    range: dict[str, str]
    summary: InferenceSummary
    warnings: list[dict[str, str]]
    points: list[ScorePoint]
    segments: list[ConfirmedSegment]
    persisted: Literal[False]
