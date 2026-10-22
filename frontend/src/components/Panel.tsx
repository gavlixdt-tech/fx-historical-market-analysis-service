import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}

/** A titled content panel used to group dashboard sections. */
export function Panel({ title, subtitle, actions, children }: PanelProps) {
  return (
    <section className="panel" aria-labelledby={`panel-${slug(title)}`}>
      <header className="panel__header">
        <div>
          <h2 className="panel__title" id={`panel-${slug(title)}`}>
            {title}
          </h2>
          {subtitle ? <p className="panel__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="panel__actions">{actions}</div> : null}
      </header>
      <div className="panel__body">{children}</div>
    </section>
  );
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
