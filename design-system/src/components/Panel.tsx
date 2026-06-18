/* Panel — a titled surface (the sidebar / pane container). Optional subsystem chip (DART/LODE/LEAP/FORGE)
 * and a header actions slot. */
import * as React from "react";
import { SubsystemChip, type Subsystem } from "./SubsystemChip";

export interface PanelProps {
  title: string;
  subsystem?: Subsystem;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}

export function Panel({ title, subsystem, actions, children }: PanelProps): JSX.Element {
  return (
    <section className="ds-panel">
      <header className="ds-panel__head">
        <h3 className="ds-panel__title">{title}</h3>
        {subsystem && <SubsystemChip name={subsystem} />}
        {actions && <span style={{ marginLeft: "auto" }}>{actions}</span>}
      </header>
      <div className="ds-panel__body">{children}</div>
    </section>
  );
}
