from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from backend.app.schemas.common import ApiResponse
from backend.app.schemas.forecasting import (
    BaselineRequest,
    BaselineResponseData,
    DatasetBuildRequest,
    DatasetBuildResponseData,
    DataSourceResponseData,
    ExperimentRunRequest,
    ExperimentRunResponseData,
    ExperimentValidationResponseData,
    FeatureConstructionRequest,
    FeatureDatasetResponseData,
    ForecastingProblemInput,
    ForecastingProblemValidationResponseData,
    ForecastingTargetsResponseData,
    HistoricalDatasetRequest,
    HistoricalDatasetResponseData,
    HistoricalProviderInventoryData,
    LabelGenerationRequest,
    LabelGenerationResponseData,
    ModelFamiliesResponseData,
    ResearchReadinessResponseData,
    SplitRequest,
    SplitResponseData,
)
from backend.app.schemas.replay import (
    HistoricalReplayRequest,
    HistoricalReplayResponseData,
)
from backend.app.schemas.replay_market_data import HistoricalReplayMarketDataRequest
from backend.app.services.forecasting_service import ForecastingService as AnalysisService
from backend.app.services.health_service import build_meta
from backend.app.services.replay_market_data import run_market_data_replay

router = APIRouter()


def get_service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.analysis_service)


@router.post(
    "/historical-replay/run",
    response_model=ApiResponse[HistoricalReplayResponseData],
)
async def run_historical_replay(
    request: Request, payload: HistoricalReplayRequest
) -> ApiResponse[HistoricalReplayResponseData]:
    from backend.app.analysis.replay import run_historical_replay as execute_replay
    from backend.app.core.errors import ValidationError as AppValidationError

    rid = getattr(request.state, "request_id", "unknown")
    if payload.synthetic and request.app.state.settings.is_production:
        raise AppValidationError("Synthetic replay fixtures are not accepted in production.")
    try:
        result = await run_in_threadpool(execute_replay, payload)
    except ValueError as exc:
        raise AppValidationError(str(exc)) from exc
    data = HistoricalReplayResponseData(**result)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post(
    "/historical-replay/run-from-market-data",
    response_model=ApiResponse[HistoricalReplayResponseData],
)
async def run_historical_replay_from_market_data(
    request: Request,
    payload: HistoricalReplayMarketDataRequest,
) -> ApiResponse[HistoricalReplayResponseData]:
    from backend.app.core.errors import ValidationError as AppValidationError

    rid = getattr(request.state, "request_id", "unknown")
    try:
        result = await run_market_data_replay(
            payload,
            settings=request.app.state.settings,
            upstream=request.app.state.upstream_client,
            request_id=rid,
        )
    except ValueError as exc:
        raise AppValidationError(str(exc)) from exc
    data = HistoricalReplayResponseData(**result)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.get("/forecasting/targets", response_model=ApiResponse[ForecastingTargetsResponseData])
async def list_targets(request: Request) -> ApiResponse[ForecastingTargetsResponseData]:
    service = get_service(request)
    rid = getattr(request.state, "request_id", "unknown")
    targets = await service.list_forecasting_targets()
    from backend.app.schemas.forecasting import ForecastingTargetDefinition

    defs = [
        ForecastingTargetDefinition(
            name=t["name"],
            formula=t["formula"],
            units=t["units"],
            description=t["description"],
        )
        for t in targets
        if "formula" in t
    ]
    data = ForecastingTargetsResponseData(targets=defs)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post(
    "/forecasting/problem/validate",
    response_model=ApiResponse[ForecastingProblemValidationResponseData],
)
async def validate_problem(
    request: Request, payload: ForecastingProblemInput
) -> ApiResponse[ForecastingProblemValidationResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    valid, errors, spec = await service.validate_forecasting_problem(payload)
    data = ForecastingProblemValidationResponseData(valid=valid, errors=errors, spec=spec)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/features", response_model=ApiResponse[FeatureDatasetResponseData])
async def construct_features(
    request: Request, payload: FeatureConstructionRequest
) -> ApiResponse[FeatureDatasetResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    valid_rows, feature_specs, excluded, instrument, timeframe = await service.construct_features(
        payload, rid
    )
    data = FeatureDatasetResponseData(
        status="completed",
        feature_rows=valid_rows,
        feature_specs=feature_specs,
        feature_count=len(valid_rows),
        excluded_rows=excluded,
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/labels", response_model=ApiResponse[LabelGenerationResponseData])
async def generate_labels(
    request: Request, payload: LabelGenerationRequest
) -> ApiResponse[LabelGenerationResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    (
        labels,
        valid_count,
        total_count,
        instrument,
        timeframe,
    ) = await service.generate_forecasting_labels(payload, rid)
    data = LabelGenerationResponseData(
        status="completed",
        labels=labels,
        valid_count=valid_count,
        total_count=total_count,
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/splits", response_model=ApiResponse[SplitResponseData])
async def create_splits(request: Request, payload: SplitRequest) -> ApiResponse[SplitResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.build_forecasting_dataset(payload, rid)
    # Reuse split portion only
    split = result["split"]
    data = SplitResponseData(
        status=split["status"],
        train_indices=split["train_indices"],
        validation_indices=split["validation_indices"],
        test_indices=split["test_indices"],
        purged_indices=split["purged_indices"],
        embargoed_indices=split["embargoed_indices"],
        counts=split["counts"],
        boundaries=split["boundaries"],
        failed_constraint=split["failed_constraint"],
        available_required=split["available_required"],
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/dataset", response_model=ApiResponse[DatasetBuildResponseData])
async def build_dataset(
    request: Request, payload: DatasetBuildRequest
) -> ApiResponse[DatasetBuildResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.build_forecasting_dataset(payload, rid)
    data = DatasetBuildResponseData(
        status=result["status"],
        manifest=result["manifest"],
        quality=result["quality"],
        split=result["split"],
        feature_count=result["feature_count"],
        label_count=result["label_count"],
        valid_label_count=result["valid_label_count"],
        baselines=result["baselines"],
        warnings=result["warnings"],
        limitations=result["limitations"],
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/baselines", response_model=ApiResponse[BaselineResponseData])
async def compute_baselines(
    request: Request, payload: BaselineRequest
) -> ApiResponse[BaselineResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    metrics = await service.compute_forecasting_baselines(payload, rid)
    data = BaselineResponseData(metrics=metrics)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.get("/forecasting/models", response_model=ApiResponse[ModelFamiliesResponseData])
async def list_model_families(
    request: Request, task_type: str | None = None
) -> ApiResponse[ModelFamiliesResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    families = await service.list_model_families(task_type)
    data = ModelFamiliesResponseData(families=families)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post(
    "/forecasting/experiment/validate", response_model=ApiResponse[ExperimentValidationResponseData]
)
async def validate_experiment(
    request: Request, payload: ExperimentRunRequest
) -> ApiResponse[ExperimentValidationResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    valid, errors, config = await service.validate_experiment(payload)
    data = ExperimentValidationResponseData(valid=valid, errors=errors, config=config)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/forecasting/experiment/run", response_model=ApiResponse[ExperimentRunResponseData])
async def run_experiment(
    request: Request, payload: ExperimentRunRequest
) -> ApiResponse[ExperimentRunResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.run_experiment(payload, rid)
    data = ExperimentRunResponseData(
        experiment_id=result["experiment_id"],
        status=result["status"],
        started_at=result["started_at"],
        completed_at=result["completed_at"],
        problem=result["problem"],
        dataset_fingerprint=result["dataset_fingerprint"],
        feature_set_version=result["feature_set_version"],
        target_type=result["target_type"],
        task_type=result["task_type"],
        n_observations=result["n_observations"],
        n_folds=result["n_folds"],
        folds=result["folds"],
        models=result["models"],
        comparison=result["comparison"],
        aggregate=result["aggregate"],
        warnings=result["warnings"],
        limitations=result["limitations"],
        artifact=result["artifact"],
        data_source=result.get("data_source"),
        synthetic=result.get("synthetic"),
        data_provenance=result.get("data_provenance"),
        random_seed=result.get("random_seed"),
        validation_scheme=result.get("validation_scheme"),
        purge=result.get("purge"),
        embargo_periods=result.get("embargo_periods"),
        reproducibility=result.get("reproducibility"),
        effective_config=result.get("effective_config"),
        research_readiness_status=result.get("research_readiness_status"),
        research_readiness=result.get("research_readiness"),
        code_version=result.get("code_version"),
        git_commit=result.get("git_commit"),
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.get(
    "/forecasting/experiment/{experiment_id}", response_model=ApiResponse[ExperimentRunResponseData]
)
async def get_experiment(
    request: Request, experiment_id: str
) -> ApiResponse[ExperimentRunResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = service.get_experiment(experiment_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="experiment not found")
    data = ExperimentRunResponseData(
        experiment_id=result["experiment_id"],
        status=result["status"],
        started_at=result["started_at"],
        completed_at=result["completed_at"],
        problem=result["problem"],
        dataset_fingerprint=result["dataset_fingerprint"],
        feature_set_version=result["feature_set_version"],
        target_type=result["target_type"],
        task_type=result["task_type"],
        n_observations=result["n_observations"],
        n_folds=result["n_folds"],
        folds=result["folds"],
        models=result["models"],
        comparison=result["comparison"],
        aggregate=result["aggregate"],
        warnings=result["warnings"],
        limitations=result["limitations"],
        artifact=result["artifact"],
        data_source=result.get("data_source"),
        synthetic=result.get("synthetic"),
        data_provenance=result.get("data_provenance"),
        random_seed=result.get("random_seed"),
        validation_scheme=result.get("validation_scheme"),
        purge=result.get("purge"),
        embargo_periods=result.get("embargo_periods"),
        reproducibility=result.get("reproducibility"),
        effective_config=result.get("effective_config"),
        research_readiness_status=result.get("research_readiness_status"),
        research_readiness=result.get("research_readiness"),
        code_version=result.get("code_version"),
        git_commit=result.get("git_commit"),
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.get("/forecasting/experiment/{experiment_id}/folds")
async def get_experiment_folds(request: Request, experiment_id: str) -> ApiResponse[dict[str, Any]]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = service.get_experiment(experiment_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="experiment not found")
    return ApiResponse(
        data={"folds": result["folds"], "models": result["models"]},
        meta=build_meta(request.app.state.settings, rid),
    )


@router.get("/forecasting/experiment/{experiment_id}/comparison")
async def get_experiment_comparison(
    request: Request, experiment_id: str
) -> ApiResponse[dict[str, Any]]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = service.get_experiment(experiment_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="experiment not found")
    return ApiResponse(
        data={"comparison": result["comparison"], "aggregate": result["aggregate"]},
        meta=build_meta(request.app.state.settings, rid),
    )


@router.get("/forecasting/experiment/{experiment_id}/limitations")
async def get_experiment_limitations(
    request: Request, experiment_id: str
) -> ApiResponse[dict[str, Any]]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = service.get_experiment(experiment_id)
    if result is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="experiment not found")
    return ApiResponse(
        data={
            "warnings": result["warnings"],
            "limitations": result["limitations"],
            "artifact": result["artifact"],
        },
        meta=build_meta(request.app.state.settings, rid),
    )


@router.get("/data-source", response_model=ApiResponse[DataSourceResponseData])
async def data_source(request: Request) -> ApiResponse[DataSourceResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.check_data_source(rid)
    data = DataSourceResponseData(
        configuration=result["configuration"],
        connectivity=result["connectivity"],
        contract_status=result["contract_status"],
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.get(
    "/historical-data/providers",
    response_model=ApiResponse[HistoricalProviderInventoryData],
)
async def historical_providers(
    request: Request,
) -> ApiResponse[HistoricalProviderInventoryData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.list_historical_providers(rid)
    data = HistoricalProviderInventoryData(**result)
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/historical-data/retrieve", response_model=ApiResponse[HistoricalDatasetResponseData])
async def retrieve_historical_data(
    request: Request, payload: HistoricalDatasetRequest
) -> ApiResponse[HistoricalDatasetResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.retrieve_historical_dataset(payload, rid)
    data = HistoricalDatasetResponseData(
        status=result["status"],
        data_source=result["data_source"],
        synthetic=result["synthetic"],
        instrument=result["instrument"],
        timeframe=result["timeframe"],
        price_basis=result["price_basis"],
        provider_id=result["provider_id"],
        observations=result["observations"],
        quality=result["quality"],
        provenance=result["provenance"],
        dataset_fingerprint=result["dataset_fingerprint"],
        partial=result["partial"],
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))


@router.post("/research/readiness", response_model=ApiResponse[ResearchReadinessResponseData])
async def research_readiness(
    request: Request, payload: ExperimentRunRequest
) -> ApiResponse[ResearchReadinessResponseData]:
    rid = getattr(request.state, "request_id", "unknown")
    service = get_service(request)
    result = await service.assess_research_readiness(payload, rid)
    data = ResearchReadinessResponseData(
        ready=result["ready"],
        findings=result["findings"],
        experiment_validation=result["experiment_validation"],
        dataset_quality=result["dataset_quality"],
        readiness_status=result.get("readiness_status"),
        research_readiness_status=result.get("research_readiness_status"),
    )
    return ApiResponse(data=data, meta=build_meta(request.app.state.settings, rid))
