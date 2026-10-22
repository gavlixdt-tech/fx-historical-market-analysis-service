import { EmptyState } from "@/components/EmptyState";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import type { CapabilityStatus } from "@/schemas/api";

interface AnalysisWorkspaceProps {
  capabilities: CapabilityStatus[];
  isLoading: boolean;
}

/**
 * Historical Analysis Workspace.
 *
 * This is a RESERVED workspace. The historical analysis engine is not
 * implemented in this foundation phase, so no statistics, patterns, regimes,
 * or scores are shown. The panel lists which analytical capabilities are
 * planned and explicitly marks each one as not implemented.
 *
 * Nothing in this component is ever derived from market data.
 */
export function AnalysisWorkspace({
  capabilities,
  isLoading,
}: AnalysisWorkspaceProps) {
  const deferred = capabilities.filter((c) => !c.implemented);
  const implemented = capabilities.filter((c) => c.implemented);

  return (
    <Panel
      title="Historical Analysis Workspace"
      subtitle="Reserved for the historical analysis engine (not implemented in this phase)."
    >
      <div
        className="not-implemented-banner"
        role="status"
        data-testid="analysis-not-implemented"
      >
        <StatusBadge tone="info" label="Not implemented" />
        <p className="not-implemented-banner__text">
          The historical analysis engine has not been implemented. This
          workspace is reserved and intentionally displays no market
          statistics, historical patterns, regime classifications, or analysis
          scores.
        </p>
      </div>

      {isLoading ? <p className="muted">Loading capability manifest…</p> : null}

      {deferred.length === 0 && !isLoading ? (
        <EmptyState
          title="No capability manifest"
          message="The backend did not report any deferred analytical capabilities."
        />
      ) : null}

      {deferred.length > 0 ? (
        <ul className="capability-list" data-testid="deferred-capabilities">
          {deferred.map((capability) => (
            <li key={capability.name} className="capability-list__item">
              <div className="capability-list__head">
                <span className="capability-list__name">
                  {capability.name.replace(/_/g, " ")}
                </span>
                <StatusBadge tone="neutral" label="deferred" />
              </div>
              {capability.detail ? (
                <p className="capability-list__detail">{capability.detail}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {implemented.length > 0 ? (
        <>
          <h3 className="section-subtitle">Currently implemented</h3>
          <ul className="capability-list" data-testid="implemented-capabilities">
            {implemented.map((capability) => (
              <li key={capability.name} className="capability-list__item">
                <div className="capability-list__head">
                  <span className="capability-list__name">
                    {capability.name.replace(/_/g, " ")}
                  </span>
                  <StatusBadge tone="ok" label="available" />
                </div>
                {capability.detail ? (
                  <p className="capability-list__detail">{capability.detail}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Panel>
  );
}
