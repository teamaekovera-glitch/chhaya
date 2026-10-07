/** Comparison-chip formatting — pure functions, unit-covered in format.test.ts. */

export function formatDistance(metres: number): string {
  if (!Number.isFinite(metres) || metres < 0) return '—'
  if (metres >= 1000) {
    const km = metres / 1000
    return `${km >= 10 ? Math.round(km) : Math.round(km * 10) / 10} km`
  }
  return `${Math.round(metres)} m`
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const minutes = seconds / 60
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60)
    const m = Math.round(minutes - h * 60)
    return m > 0 ? `${h} h ${m} min` : `${h} h`
  }
  return `${Math.max(1, Math.round(minutes))} min`
}

/** Shade fraction 0..1 → percent chip label. */
export function formatShade(fraction: number): string {
  if (!Number.isFinite(fraction)) return '—'
  return `${Math.round(fraction * 100)}% shaded`
}

/** Flood risk 0..1 → chip label. Undefined outside flood mode. */
export function formatFlood(risk: number | undefined): string | undefined {
  if (risk === undefined || !Number.isFinite(risk)) return undefined
  const pct = Math.round(risk * 100)
  return pct <= 20 ? `${pct}% flood risk (low)` : `${pct}% flood risk`
}

/** Signed delta chip, e.g. "+6 min · +480 m" versus the baseline. */
export function formatDelta(
  extraSeconds: number,
  extraMetres: number,
): string | undefined {
  if (!Number.isFinite(extraSeconds) || !Number.isFinite(extraMetres)) return undefined
  const mins = Math.round(extraSeconds / 60)
  const metres = Math.round(extraMetres)
  return `+${mins} min · +${metres} m`
}
