/** IST slot logic — mirrors lambdas/route/handler.py `slot_from_time` (§8.3):
 *  slot i = 07:00 + 15·i minutes, i ∈ [0..47]. IST = UTC+05:30 fixed (§6.1).
 *  A request outside 07:00–18:59 clamps to the nearest slot. */

import { SLOTS } from './types'

export const SLOT_START_MIN = 7 * 60

export interface Slot {
  /** Index into the 48-slot strip (0..47). */
  index: number
  /** IST time label, 'HH:MM'. */
  label: string
}

/** All 48 slots with their IST time labels (07:00 … 18:45). */
export function allSlots(): Slot[] {
  return Array.from({ length: SLOTS }, (_, index) => ({
    index,
    label: slotTimeLabel(index),
  }))
}

export function slotTimeLabel(index: number): string {
  const minutes = SLOT_START_MIN + index * 15
  const hh = Math.floor(minutes / 60)
  const mm = minutes % 60
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
}

/** Current IST time as a strip index. Never clamps (computed inside the day). */
export function currentSlotIndex(nowIstMs = Date.now()): number {
  const minutesInIst = (Math.floor(nowIstMs / 60000) + 330) % 1440
  const raw = Math.round((minutesInIst - SLOT_START_MIN) / 15)
  return Math.max(0, Math.min(SLOTS - 1, raw))
}

/** Four axis labels for the strip endpoints (§10 brief: 00/06/12/18/24 ticks).
 *  The strip spans 07:00–18:45, so its endpooints are the tick anchors. */
export function stripTickLabels(): string[] {
  const last = SLOTS - 1
  return [
    slotTimeLabel(0),
    slotTimeLabel(Math.round(last * (6 / 24))),
    slotTimeLabel(Math.round(last * (12 / 24))),
    slotTimeLabel(Math.round(last * (18 / 24))),
    slotTimeLabel(last),
  ]
}
