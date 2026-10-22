interface DataRowProps {
  label: string;
  value: React.ReactNode;
  testId?: string;
}

/** A single label/value pair inside a detail list. */
export function DataRow({ label, value, testId }: DataRowProps) {
  return (
    <div className="data-row">
      <dt className="data-row__label">{label}</dt>
      <dd className="data-row__value" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}
