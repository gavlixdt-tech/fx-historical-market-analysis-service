import { useState, type ChangeEvent, type FormEvent } from "react";

import { EmptyState } from "@/components/EmptyState";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LoadingState } from "@/components/LoadingState";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError, type SessionLiquidityEventStudyResponseData } from "@/services/api";

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function numberOrLabel(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "Not estimable";
}

/**
 * Research-only view for the existing session/liquidity event-study endpoint.
 * Input events are caller-supplied; this page does not claim automatic Service
 * 18 ingestion, producer authentication, persistence, or forecast eligibility.
 */
export function SessionLiquidityEventStudy() {
  const [payload, setPayload] = useState<JsonRecord | null>(null);
  const [fileName, setFileName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<SessionLiquidityEventStudyResponseData | null>(null);

  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    setError(null);
    setResult(null);
    if (!file) return;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      const candidate = asRecord(parsed);
      if (
        typeof candidate.analysis_cutoff !== "string" ||
        !Array.isArray(candidate.events) ||
        candidate.events.length < 1 ||
        candidate.events.length > 10000
      ) {
        throw new Error("Expected { analysis_cutoff, events, minimum_group_sample? } with 1–10,000 events.");
      }
      if (Number.isNaN(Date.parse(candidate.analysis_cutoff))) {
        throw new Error("analysis_cutoff must be a valid timestamp.");
      }
      setPayload(candidate);
      setFileName(file.name);
    } catch (caught) {
      setPayload(null);
      setFileName("");
      setError(new ApiError(
        caught instanceof Error ? caught.message : "Invalid event-study JSON.",
        0,
        "INVALID_EVENT_STUDY_FILE",
        null,
      ));
    }
  }

  async function runStudy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!payload) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.runSessionLiquidityEventStudy(payload));
    } catch (caught) {
      setError(caught instanceof ApiError
        ? caught
        : new ApiError("The event study could not be completed.", 0, "UNEXPECTED", null));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Panel
      title="Session & Liquidity Event Study"
      subtitle="Descriptive historical event study with explicit availability cutoff and right-censored lifecycle estimates."
    >
      <div data-testid="session-liquidity-event-study">
        <p className="not-implemented-banner">
          This endpoint accepts caller-supplied event records. Automatic Service 18 ingestion, independent producer authentication, durable event storage, and forecast-feature approval are not implemented. Results are view-only research evidence.
        </p>
        <form className="replay-form" onSubmit={runStudy}>
          <label>
            Event-study JSON file
            <input type="file" accept=".json,application/json" onChange={loadFile} data-testid="event-study-file" />
          </label>
          <p className="muted small">
            {fileName ? fileName : "Expected a JSON object containing analysis_cutoff and an events array (maximum 10,000)."}
          </p>
          <button className="button" type="submit" disabled={!payload || loading} data-testid="run-event-study">
            {loading ? "Calculating event study…" : "Run descriptive event study"}
          </button>
        </form>
        {loading ? <LoadingState label="Calculating first-sweep and lifecycle distributions…" /> : null}
        {error ? (
          <ErrorNotice title="Event study unavailable" message={error.message} code={error.code} requestId={error.requestId} testId="event-study-error" />
        ) : null}
        {result ? (
          <section data-testid="event-study-result" className="replay-result">
            <div className="integration-head">
              <p className="integration-head__service">Analysis {result.analysis_id.slice(0, 16)}</p>
              <StatusBadge tone={result.forecast_eligible ? "ok" : "warn"} label={result.forecast_eligible ? "forecast eligible" : "descriptive only"} />
            </div>
            <div className="overview-grid">
              <div className="overview-card"><p className="overview-card__label">Input events</p><p className="overview-card__value">{result.input_event_count}</p></div>
              <div className="overview-card"><p className="overview-card__label">Eligible at cutoff</p><p className="overview-card__value">{result.eligible_event_count}</p></div>
              <div className="overview-card"><p className="overview-card__label">Excluded after cutoff</p><p className="overview-card__value">{result.excluded_after_cutoff_count}</p></div>
              <div className="overview-card"><p className="overview-card__label">First-sweep sessions</p><p className="overview-card__value">{result.first_sweep_session_instance_count}</p></div>
            </div>
            <p className="muted small">Cutoff: {result.analysis_cutoff} · Provenance: {result.provenance_status}</p>
            {result.groups.length === 0 ? (
              <EmptyState title="No eligible events" message="No supplied event was available by the analysis cutoff." />
            ) : (
              result.groups.map((rawGroup, index) => {
                const group = asRecord(rawGroup);
                const distribution = asRecord(group.minutes_from_session_open_to_first_confirmed_sweep);
                const directions = asRecord(group.first_sweep_direction_counts);
                const displacement = asRecord(group.post_sweep_time_to_displacement);
                const midpoint = asRecord(group.post_sweep_time_to_midpoint);
                const consolidation = asRecord(group.post_sweep_time_to_consolidation_candidate);
                const invalidation = asRecord(group.post_sweep_time_to_invalidation);
                const sampleSufficient = group.sample_status === "sufficient_for_descriptive_estimate";
                return (
                  <section key={String(group.instrument) + String(group.timeframe) + String(group.session_key) + index}>
                    <h3 className="section-subtitle">{String(group.instrument)} · {String(group.timeframe)} · {String(group.session_key).replace(/_/g, " ")}</h3>
                    <StatusBadge tone={sampleSufficient ? "ok" : "warn"} label={sampleSufficient ? "descriptive sample threshold met" : "insufficient sample"} />
                    <dl className="data-list">
                      <div className="data-row"><dt className="data-row__label">Session instances</dt><dd className="data-row__value">{display(group.first_sweep_session_instances)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Minutes to first sweep (median / p75 / p90)</dt><dd className="data-row__value">{numberOrLabel(distribution.median)} / {numberOrLabel(distribution.p75)} / {numberOrLabel(distribution.p90)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Bullish / bearish first sweeps</dt><dd className="data-row__value">{display(directions.bullish)} / {display(directions.bearish)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Displacement (events / censored / median min)</dt><dd className="data-row__value">{display(displacement.events)} / {display(displacement.censored)} / {numberOrLabel(displacement.median_minutes)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Midpoint (events / censored / median min)</dt><dd className="data-row__value">{display(midpoint.events)} / {display(midpoint.censored)} / {numberOrLabel(midpoint.median_minutes)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Consolidation (events / censored / median min)</dt><dd className="data-row__value">{display(consolidation.events)} / {display(consolidation.censored)} / {numberOrLabel(consolidation.median_minutes)}</dd></div>
                      <div className="data-row"><dt className="data-row__label">Invalidation (events / censored / median min)</dt><dd className="data-row__value">{display(invalidation.events)} / {display(invalidation.censored)} / {numberOrLabel(invalidation.median_minutes)}</dd></div>
                    </dl>
                    <p className="muted small">Source event IDs: {Array.isArray(group.source_event_ids) ? group.source_event_ids.join(", ") : "Not reported"}</p>
                  </section>
                );
              })
            )}
            <h3 className="section-subtitle">Limitations</h3>
            <ul>{result.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
            <p className="muted small">This result is descriptive only. It is not a forward forecast, calibrated probability, entry signal, or trade recommendation.</p>
          </section>
        ) : null}
      </div>
    </Panel>
  );
}

function display(value: unknown): string {
  return value === null || value === undefined ? "Not reported" : String(value);
}
