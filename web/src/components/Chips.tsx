import { BASELINE_COLOR, DIRECT_COLOR, chhayaColor } from '../map/draw'
import type { Season } from '../types'

export interface Chip {
  label: string
  value: string
  tone?: 'neutral' | 'good' | 'warn'
}

/** Comparison chips row — wraps on small screens (§6.7). */
export function ChipRow({ chips }: { chips: Chip[] }) {
  if (chips.length === 0) return null
  return (
    <div className="chip-row" data-testid="chip-row">
      {chips.map((chip) => (
        <span key={chip.label} className={`chip chip--${chip.tone ?? 'neutral'}`}>
          <span className="chip__label">{chip.label}</span>
          <span className="chip__value">{chip.value}</span>
        </span>
      ))}
    </div>
  )
}

export function Legend({ season }: { season: Season }) {
  return (
    <div className="legend" data-testid="legend">
      <LegendItem label="Direct" color={DIRECT_COLOR} />
      <LegendItem
        label={season === 'summer' ? 'Chhaya (cooler)' : 'Chhaya (keep dry)'}
        color={chhayaColor(season)}
      />
      <LegendItem label="Baseline (Location)" color={BASELINE_COLOR} dashed />
    </div>
  )
}

function LegendItem({ label, color, dashed }: { label: string; color: string; dashed?: boolean }) {
  return (
    <span className="legend__item">
      <svg className="legend__swatch" width="20" height="6" aria-hidden="true">
        <line
          x1="0"
          y1="3"
          x2="20"
          y2="3"
          stroke={color}
          strokeWidth="3"
          strokeDasharray={dashed ? '3 3' : undefined}
          strokeLinecap="round"
        />
      </svg>
      {label}
    </span>
  )
}
