import { describe, expect, it } from 'vitest'
import {
  formatDelta,
  formatDistance,
  formatDuration,
  formatFlood,
  formatShade,
} from './format'

describe('formatDistance', () => {
  it('renders metres below 1 km', () => {
    expect(formatDistance(850)).toBe('850 m')
  })
  it('renders kilometres with one decimal below 10 km', () => {
    expect(formatDistance(1420)).toBe('1.4 km')
  })
  it('rounds whole km at 10 km and above', () => {
    expect(formatDistance(12300)).toBe('12 km')
  })
  it('collapses invalid input to an em dash', () => {
    expect(formatDistance(Number.NaN)).toBe('—')
  })
})

describe('formatDuration', () => {
  it('renders minutes', () => {
    expect(formatDuration(1092)).toBe('18 min')
  })
  it('never lets a sub-minute walk read as 0 min', () => {
    expect(formatDuration(20)).toBe('1 min')
  })
  it('renders hours above 60 min', () => {
    expect(formatDuration(3600)).toBe('1 h')
    expect(formatDuration(3720)).toBe('1 h 2 min')
  })
  it('collapses invalid input to an em dash', () => {
    expect(formatDuration(Number.POSITIVE_INFINITY)).toBe('—')
  })
})

describe('formatShade', () => {
  it('renders fractions as rounded percent', () => {
    expect(formatShade(0.65)).toBe('65% shaded')
    expect(formatShade(0.211)).toBe('21% shaded')
  })
})

describe('formatFlood', () => {
  it('is dropped outside flood mode', () => {
    expect(formatFlood(undefined)).toBeUndefined()
  })
  it('marks low risk explicitly', () => {
    expect(formatFlood(0.12)).toBe('12% flood risk (low)')
  })
  it('renders plain percent above the low threshold', () => {
    expect(formatFlood(0.31)).toBe('31% flood risk')
  })
})

describe('formatDelta', () => {
  it('formats the vs-direct delta on both axes', () => {
    expect(formatDelta(366, 480)).toBe('+6 min · +480 m')
  })
  it('is dropped when either input is missing', () => {
    expect(formatDelta(Number.NaN, 100)).toBeUndefined()
    expect(formatDelta(60, Number.NaN)).toBeUndefined()
  })
})
