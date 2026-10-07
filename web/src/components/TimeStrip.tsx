import { allSlots, slotTimeLabel, stripTickLabels } from '../timeSlots'
import { ShadeSparkline } from './Sparkline'

export interface TimeStripProps {
  selected: number
  onSelect: (index: number) => void
  disabled?: boolean
  /** Route shade_profile[48] — drawn behind the strip as a sparkline. */
  shadeProfile?: number[]
}

/** 48-slot departure strip, 07:00–18:45 IST (§6.2). Native range input for
 *  touch friendliness; tick labels at the five day-marks; the current
 *  slot's shade profile is the backdrop. */
export function TimeStrip({ selected, onSelect, disabled, shadeProfile }: TimeStripProps) {
  return (
    <div className={`time-strip${disabled ? ' time-strip--disabled' : ''}`} data-testid="time-strip">
      <div className="time-strip__spark">
        {shadeProfile ? <ShadeSparkline values={shadeProfile} highlight={selected} /> : null}
      </div>
      <input
        type="range"
        min={0}
        max={47}
        step={1}
        value={selected}
        disabled={disabled}
        aria-label={`Departure time, ${slotTimeLabel(selected)} IST`}
        onChange={(e) => {
          const v = Number(e.target.value)
          if (Number.isInteger(v)) onSelect(Math.max(0, Math.min(47, v)))
        }}
        data-testid="time-strip-range"
      />
      <div className="time-strip__ticks" aria-hidden="true">
        {stripTickLabels().map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <output className="time-strip__value" data-testid="time-strip-value">
        Departs {slotTimeLabel(selected)} IST
      </output>
      <datalist id="time-strip-ticks">
        {allSlots().map((slot) => (
          <option key={slot.index} value={slot.index} label={slot.label} />
        ))}
      </datalist>
    </div>
  )
}
