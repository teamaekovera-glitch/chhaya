import { describe, expect, it } from 'vitest'
import { currentSlotIndex, slotTimeLabel, stripTickLabels } from './timeSlots'

describe('slotTimeLabel', () => {
  it('labels slot 0 as 07:00', () => {
    expect(slotTimeLabel(0)).toBe('07:00')
  })
  it('labels slot 26 as 13:30 (departure default)', () => {
    expect(slotTimeLabel(26)).toBe('13:30')
  })
  it('labels the last slot as 18:45', () => {
    expect(slotTimeLabel(47)).toBe('18:45')
  })
})

describe('currentSlotIndex', () => {
  it('maps noon IST inside the day without clamping', () => {
    const utcNoon = Date.UTC(2026, 4, 15, 6, 30) // 12:00:00 IST (offset +5:30)
    expect(slotTimeLabel(currentSlotIndex(utcNoon))).toBe('12:00')
  })
  it('clamps pre-07:00 IST to the first slot', () => {
    const before07 = Date.UTC(2026, 4, 15, 1, 0) // 06:30 IST
    expect(currentSlotIndex(before07)).toBe(0)
  })
  it('clamps post-19:00 IST to the last slot', () => {
    const late = Date.UTC(2026, 4, 15, 14, 30) // 20:00 IST
    expect(currentSlotIndex(late)).toBe(47)
  })
})

describe('stripTickLabels', () => {
  it('starts and ends on the strip endpoints with five day-marks', () => {
    const labels = stripTickLabels()
    expect(labels).toHaveLength(5)
    expect(labels[0]).toBe('07:00')
    expect(labels[labels.length - 1]).toBe('18:45')
  })
})
