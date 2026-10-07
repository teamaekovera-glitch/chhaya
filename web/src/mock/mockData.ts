/** Synthetic data for ?mock=1 — DEV/SCREENSHOT ONLY.
 *
 *  Never imported by the app runtime: main.tsx swaps api calls to these only
 *  when the query flag is present, so the hackathon judges never see mock data
 *  and the committed bundle ships no mock path. Purpose: the sandbox and the
 *  visual-QA loop have no AWS credentials and no Location key, so route search,
 *  place search, and the baseline are all stubbed here with deterministic
 *  shapes consistent with the Phase 3 contract.
 *
 *  Scenario = the decision sheet's Karol Bagh preset:
 *  Karol Bagh Metro Station → Junction of Ranjit Singh Flyover + Padam Singh Rd.
 */

import type { BaselineRoute, Mode, RouteResult, Season } from '../types'

export const MOCK_ORIGIN: [number, number] = [77.1835, 28.6446]
export const MOCK_DESTINATION: [number, number] = [77.2015, 28.6546]
export const MOCK_ORIGIN_NAME = 'Karol Bagh Metro Station'
export const MOCK_DESTINATION_NAME = 'Junction of Ranjit Singh Flyover + Padam Singh Road'

const DIRECT: [number, number][] = [
  [77.1835, 28.6446],
  [77.1860, 28.6455],
  [77.1895, 28.6468],
  [77.1930, 28.6482],
  [77.1965, 28.6497],
  [77.2000, 28.6520],
  [77.2015, 28.6546],
]

/** Doglegs north through inner mohalla blocks — visibly off the direct line. */
const SHADE: [number, number][] = [
  [77.1835, 28.6446],
  [77.1855, 28.6460],
  [77.1875, 28.6478],
  [77.1890, 28.6495],
  [77.1910, 28.6510],
  [77.1950, 28.6530],
  [77.2015, 28.6546],
]

/** Curves wider north, avoiding the low southern segment past the flyover. */
const FLOOD: [number, number][] = [
  [77.1835, 28.6446],
  [77.1845, 28.6465],
  [77.1860, 28.6490],
  [77.1885, 28.6510],
  [77.1925, 28.6525],
  [77.1970, 28.6538],
  [77.2015, 28.6546],
]

const GEOMETRIES: Record<Mode, [number, number][]> = {
  direct: DIRECT,
  shade: SHADE,
  flood: FLOOD,
}

const DISTANCES_M: Record<Mode, number> = { direct: 1420, shade: 1620, flood: 1550 }

/** Deterministic 48-slot profiles; shade_score follows the requested slot. */
function makeProfile(mode: Mode): number[] {
  return Array.from({ length: 48 }, (_, s) => {
    const f = s / 47
    let v: number
    if (mode === 'shade') v = 0.45 + 0.4 * Math.sin(Math.PI * f)
    else if (mode === 'flood') v = 0.3 + 0.15 * Math.sin(Math.PI * f)
    else v = 0.18 + 0.2 * f
    return Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000
  })
}

export function mockRouteResult(mode: Mode, season: Season, slot: number): RouteResult {
  const profile = makeProfile(mode)
  const distanceM = DISTANCES_M[mode]
  return {
    route: GEOMETRIES[mode],
    distance_m: distanceM,
    duration_s: distanceM / 1.1, // Phase 3 walk speed default
    shade_profile: profile,
    shade_score: profile[Math.max(0, Math.min(47, slot))],
    flood_profile: { summer: 0.22, monsoon: mode === 'flood' ? 0.12 : 0.38 },
    mode,
    season,
    slot,
    slot_time: '',
    clamped: false,
  }
}

export function mockBaseline(): BaselineRoute {
  return {
    geometry: DIRECT.map(([lon, lat], i) =>
      i === 2 ? [lon + 0.0006, lat] : [lon, lat],
    ),
    distance_m: 1390,
    duration_s: 1390 / 0.9,
  }
}

/** Static mini-index standing in for Places SearchText under ?mock=1. */
const PLACES: Array<{ title: string; position: [number, number] }> = [
  { title: 'Karol Bagh Metro Station', position: [77.1835, 28.6446] },
  { title: 'Junction of Ranjit Singh Flyover + Padam Singh Road', position: [77.2015, 28.6546] },
  { title: 'Ajmal Khan Road (shopping street)', position: [77.1903, 28.6511] },
  { title: 'Jhandewalan Metro Station', position: [77.1794, 28.6513] },
  { title: 'Fateh Nagar market', position: [77.1816, 28.6504] },
  { title: 'Bedmi Puri stall, Chitragupta Road', position: [77.1961, 28.6470] },
]

export function mockPlaces(query: string): Array<{ title: string; position: [number, number] }> {
  const q = query.trim().toLowerCase()
  if (!q) return []
  return PLACES.filter((p) => p.title.toLowerCase().includes(q)).slice(0, 5)
}
