/** Inline-SVG sparkline for the 48-slot shade/flood profile — no extra dep. */

export interface ShadeSparklineProps {
  /** Profile values in 0..1 across the 48 slots. */
  values: number[]
  /** Slot index to ring — the currently selected departure slot. */
  highlight?: number
}

const W = 240
const H = 32

export function ShadeSparkline({ values, highlight }: ShadeSparklineProps) {
  const n = values.length
  if (n < 2) return null
  const stepX = W / (n - 1)
  const x = (i: number) => (i * stepX).toFixed(2)
  const y = (v: number) => (H - Math.min(1, Math.max(0, v)) * H).toFixed(2)
  const points = values.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  return (
    <svg
      className="sparkline-svg"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Shade through the day; higher curve means more shade"
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        vectorEffect="non-scaling-stroke"
      />
      {highlight !== undefined && values[highlight] !== undefined && (
        <circle
          cx={x(highlight)}
          cy={y(values[highlight])}
          r="3"
          fill="currentColor"
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  )
}
