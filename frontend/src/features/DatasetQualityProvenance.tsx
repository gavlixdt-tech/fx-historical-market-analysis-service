import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import type { HistoricalDatasetResponseData } from "@/schemas/api";

interface DatasetQualityProvenanceProps {
  dataset: HistoricalDatasetResponseData;
}

type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not reported";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString() : "Not valid";
  if (typeof value === "string") return value;
  return JSON.stringify(value) ?? String(value);
}

function DetailList({ title, values }: { title: string; values: JsonRecord }) {
  const entries = Object.entries(values);
  return (
    <section>
      <h3 className="section-subtitle">{title}</h3>
      {entries.length === 0 ? (
        <p className="muted small">No fields were reported by the backend.</p>
      ) : (
        <dl className="data-list">
          {entries.map(([key, value]) => (
            <div className="data-row" key={key}>
              <dt className="data-row__label">{key.replace(/_/g, " ")}</dt>
              <dd className="data-row__value">{displayValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

/**
 * Displays the provenance and quality evidence attached to the retrieved
 * dataset. It intentionally consumes the retrieval response; it does not
 * invent a separate /provenance endpoint or infer authenticity from provider
 * names.
 */
export function DatasetQualityProvenance({ dataset }: DatasetQualityProvenanceProps) {
  const provenance = asRecord(dataset.provenance);
  const quality = asRecord(dataset.quality);
  const providerType = provenance.provider_type;
  const provenanceStatus = String(provenance.provenance_status ?? "unknown");
  const verified = provenance.verified_real_market_data === true;
  const researchAccepted = provenance.real_market_research_accepted === true;
  const synthetic = dataset.synthetic || providerType === "test" || providerType === "synthetic";

  return (
    <Panel
      title="Dataset Quality & Provenance"
      subtitle="Evidence returned with the selected historical dataset. Source identity alone does not verify authenticity."
    >
      <div data-testid="dataset-quality-provenance">
        <div className="integration-head">
          <p className="integration-head__service">{dataset.provider_id}</p>
          <StatusBadge
            tone={synthetic ? "warn" : verified ? "ok" : "neutral"}
            label={synthetic ? "synthetic fixture" : verified ? "verified real-market data" : "source unverified"}
          />
        </div>
        <div className="overview-grid">
          <div className="overview-card">
            <p className="overview-card__label">Instrument / timeframe</p>
            <p className="overview-card__value">{dataset.instrument} · {dataset.timeframe}</p>
          </div>
          <div className="overview-card">
            <p className="overview-card__label">Observations</p>
            <p className="overview-card__value">{dataset.observations.length.toLocaleString()}</p>
          </div>
          <div className="overview-card">
            <p className="overview-card__label">Provenance status</p>
            <p className="overview-card__value">{provenanceStatus}</p>
          </div>
          <div className="overview-card">
            <p className="overview-card__label">Research acceptance</p>
            <p className="overview-card__value">{researchAccepted ? "Accepted by backend" : "Not accepted / not verified"}</p>
          </div>
        </div>
        {synthetic ? (
          <p className="error-notice" role="status">
            This dataset is identified as synthetic/test data. It must not be treated as genuine market evidence.
          </p>
        ) : !verified ? (
          <p className="not-implemented-banner" role="status">
            The upstream source has not been independently verified as genuine real-market data. A non-test provider name is not proof of authenticity.
          </p>
        ) : null}
        <p className="muted small">
          Real-market verification: {verified ? "explicitly reported by backend" : "not established"}.
          Research eligibility: {researchAccepted ? "explicitly accepted by backend" : "not established"}.
          Partial retrieval: {dataset.partial ? "yes" : "no"}.
        </p>
        <DetailList title="Quality metrics reported by backend" values={quality} />
        <DetailList title="Provenance evidence reported by backend" values={provenance} />
        <section>
          <h3 className="section-subtitle">Dataset identity</h3>
          <p><code>{dataset.dataset_fingerprint}</code></p>
          <p className="muted small">Fingerprint is supplied by the backend and identifies this dataset response; it is not a source-authenticity certificate.</p>
        </section>
      </div>
    </Panel>
  );
}
