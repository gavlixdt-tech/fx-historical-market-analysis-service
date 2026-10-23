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
  const implemented = capabilities.filter((c) => c.implemented);

  return (
    <Panel
      title="Historical Analysis Workspace"
      subtitle="Historical analysis engine is available (research/simulation only)."
    >
      {isLoading ? <p className="muted">Loading capability manifest…</p> : null}

      {implemented.length > 0 ? (
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
      ) : null}
    </Panel>
  );
}
