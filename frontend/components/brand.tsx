/** The Vaatun mark: a rate-card grid with the selected cell highlighted. Matches app/icon.svg. */
export function BrandMark({ size = 32 }: { size?: number }) {
  const cells = [
    [7, 7],
    [13.5, 7],
    [20, 7],
    [7, 13.5],
    [20, 13.5],
    [7, 20],
    [13.5, 20],
    [20, 20],
  ];
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="8" fill="#14606E" />
      {cells.map(([x, y]) => (
        <rect
          key={`${x}-${y}`}
          x={x}
          y={y}
          width="5"
          height="5"
          rx="1.2"
          fill="#fff"
          fillOpacity=".32"
        />
      ))}
      <rect x="13.5" y="13.5" width="5" height="5" rx="1.2" fill="#F0A92E" />
    </svg>
  );
}

export function BrandName({ className = '' }: { className?: string }) {
  return (
    <span
      className={`font-display text-[17px] font-semibold tracking-[-.02em] text-ink ${className}`}
    >
      vaatun<span className="ml-1 font-normal text-muted">rater</span>
    </span>
  );
}
