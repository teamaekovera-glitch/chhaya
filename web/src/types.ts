/** Typed mirror of the deployed Phase 3 routing contract.
 *
 *  Source of truth: lambdas/route/routing.py `RouteEngine._payload` + handler.py
 *  `_handle_route` on main (Phase 3 brief's contract, consumed by task — NOT the
 *  §6.5 sketch, which predates it: one route is returned per POST, not direct+
 *  chhaya together, and `duration_s` replaces `duration_min`).
 *
 *  POST /route  body {origin, destination, mode, season, time}
 *    -> 200: route coords (lon/lat pairs), distance_m, duration_s,
 *             shade_profile[48], shade_score, flood_profile{summer,monsoon},
 *             mode, season, slot, slot_time, clamped
 *    -> 400: {error: bad_request|outside_coverage|no_route, detail?, coverage?}
 *    -> 500: {error: internal_error}
 */
export type Mode = 'direct' | 'shade' | 'flood'
export type Season = 'summer' | 'monsoon'

export const SLOTS = 48

export interface RouteResult {
  route: [number, number][]
  distance_m: number
  duration_s: number
  shade_profile: number[]
  shade_score: number
  flood_profile: { summer: number; monsoon: number }
  mode: Mode
  season: Season
  slot: number
  slot_time: string
  clamped: boolean
}

export type CoveragePolygon = {
  type: 'Polygon' | 'MultiPolygon'
  coordinates: unknown
}

export interface RouteApiError {
  error: 'bad_request' | 'outside_coverage' | 'no_route' | 'internal_error'
  detail?: string
  coverage?: CoveragePolygon
}

export type RouteResponse = RouteResult | RouteApiError

export function isApiError(res: RouteResponse): res is RouteApiError {
  return 'error' in res
}

/** Baseline result from Amazon Location Routes CalculateRoutes (browser call). */
export interface BaselineRoute {
  geometry: [number, number][]
  distance_m: number
  duration_s: number
}
