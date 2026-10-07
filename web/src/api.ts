/** CHHAYA API client — one module for every remote call the UI makes.
 *
 *  Two remote surfaces:
 *   1. CHHAYA routing API (API Gateway → Lambda, Phase 3 contract on main).
 *   2. Amazon Location Service v2 REST endpoints, called directly from the
 *      browser with the referer-restricted API key (decision sheet, locked:
 *      baseline routes + place search run in the browser; the route Lambda's
 *      permission surface stays S3-get only — no geo-routes IAM for it).
 *
 *  No AWS SDK: Locations v2 is key-authenticated plain HTTPS JSON; a browser
 *  fetch keeps the dependency set at Phase 0's (maplibre-gl, react).
 *
 *  `fetchImpl` is injectable for unit tests and for the dev/screenshot mock
 *  (?mock=1); the committed runtime always uses global fetch.
 */

import {
  type BaselineRoute,
  type Mode,
  type RouteResponse,
  type Season,
} from './types'

/** Karol Bagh BBOX — freezes SearchText to the coverage area (decision sheet).
 *  Order (west, south, east, north) — same as pipeline/config.py and the
 *  Places v2 Filter.BoundingBox order. */
export const KAROL_BAGH_BBOX: [number, number, number, number] = [
  77.178, 28.642, 77.208, 28.657,
]

const DEFAULT_TIMEOUT_MS = 12000

export class ApiTimeoutError extends Error {
  constructor(public readonly url: string) {
    super(`request timed out after ${DEFAULT_TIMEOUT_MS}ms`)
    this.name = 'ApiTimeoutError'
  }
}

async function postJson(
  url: string,
  body: unknown,
  fetchImpl: FetchLike = fetch,
): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT_MS)
  try {
    return await fetchImpl(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiTimeoutError(url)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; signal: AbortSignal },
) => Promise<Response>

/** Route request the Phase 3 handler accepts (its `destination` key is the
 *  brief's spelling; its §6.5 `dest` alias is not used here). */
export interface RouteRequestBody {
  origin: [number, number]
  destination: [number, number]
  mode: Mode
  season: Season
  time: string
}

/** POST /route against the deployed Phase 3 Lambda.
 *  Network failure / timeout → throws; caller owns offline state.
 *  200 | error body → Response union (error shapes are values, not throws). */
export async function fetchRoute(
  apiUrl: string,
  body: RouteRequestBody,
  fetchImpl: FetchLike = fetch,
): Promise<RouteResponse> {
  const res = await postJson(`${apiUrl.replace(/\/$/, '')}/route`, body, fetchImpl)
  if (!res.ok) return { error: 'internal_error', detail: `HTTP ${res.status}` }
  return (await res.json()) as RouteResponse
}

// -- Amazon Location Places v2: SearchText (one call, coordinates included) --

export interface PlaceCandidate {
  placeId?: string
  title: string
  /** [lon, lat] */
  position: [number, number]
  addressLabel?: string
}

interface SearchTextResponse {
  ResultItems?: SearchTextItem[]
}

interface SearchTextItem {
  PlaceId?: string
  Title?: string
  Position?: number[]
  Address?: { Label?: string }
}

/** Places v2 SearchText, filtered to the Karol Bagh BBOX (docs: POST
 *  {region host}/v2/search-text?key=…; Filter.BoundingBox = [w,s,e,n];
 *  coordinates come back in the same response — no follow-up GetPlace). */
export async function searchPlaces(
  query: string,
  apiKey: string,
  region: string,
  fetchImpl: FetchLike = fetch,
): Promise<PlaceCandidate[]> {
  if (!apiKey) throw new Error('VITE_LOCATION_API_KEY is not set')
  const url = `https://places.geo.${region}.amazonaws.com/v2/search-text?key=${encodeURIComponent(apiKey)}`
  const res = await postJson(
    url,
    {
      QueryText: query,
      Filter: { BoundingBox: KAROL_BAGH_BBOX },
      MaxResults: 8,
    },
    fetchImpl,
  )
  if (!res.ok) {
    throw new Error(`Location SearchText failed: HTTP ${res.status}`)
  }
  const data = (await res.json()) as SearchTextResponse
  return (data.ResultItems ?? [])
    .filter((item): item is SearchTextItem & { Position: number[] } =>
      item.Position !== undefined)
    .map((item) => ({
      placeId: item.PlaceId,
      title: item.Title ?? 'Unnamed place',
      position: [item.Position[0], item.Position[1]] as [number, number],
      addressLabel: item.Address?.Label,
    }))
}

// -- Amazon Location Routes v2: CalculateRoutes (baseline, browser-side) --

export interface CalculateRoutesOptions {
  origin: [number, number]
  destination: [number, number]
  apiKey: string
  region: string
}

interface CalculateRoutesResponse {
  Routes?: Array<{
    Distance?: number
    Summary?: { DurationSeconds?: number; Distance?: number }
    Legs?: Array<{
      Geometry?: { Geometry?: { LineString?: number[][] } | number[][] }
    }>
  }>
}

function extractLineString(route: NonNullable<CalculateRoutesResponse['Routes']>[number]): [number, number][] {
  const leg = route.Legs?.[0]
  const geometry = leg?.Geometry?.Geometry
  if (Array.isArray(geometry) && geometry.length > 0) {
    // Simple format: array of [lng, lat] pairs; tolerate bare flat-pair rows.
    return geometry as [number, number][]
  }
  return []
}

/** Baseline pedestrian route via Location Routes v2 CalculateRoutes (docs:
 *  POST /v2/routes?key=…; Origin/Destination are [longitude, latitude];
 *  TravelMode Pedestrian; LegGeometryFormat Simple → Legs[0].Geometry.Geometry
 *  is an array of [lng, lat]).
 *  Any failure → undefined (§6.5's "null baseline" contract for the browser
 *  path): baseline is honest third-line, never a gate. */
export async function fetchBaselineRoute(
  options: CalculateRoutesOptions,
  fetchImpl: FetchLike = fetch,
): Promise<BaselineRoute | undefined> {
  const { origin, destination, apiKey, region } = options
  if (!apiKey) return undefined
  const url = `https://routes.geo.${region}.amazonaws.com/v2/routes?key=${encodeURIComponent(apiKey)}`
  try {
    const res = await postJson(
      url,
      {
        Origin: origin,
        Destination: destination,
        TravelMode: 'Pedestrian',
        LegGeometryFormat: 'Simple',
      },
      fetchImpl,
    )
    if (!res.ok) return undefined
    const data = (await res.json()) as CalculateRoutesResponse
    const route = data.Routes?.[0]
    if (!route) return undefined
    const geometry = extractLineString(route)
    if (geometry.length < 2) return undefined
    const distance = route.Distance ?? route.Summary?.Distance
    return {
      geometry,
      distance_m: typeof distance === 'number' ? distance : 0,
      duration_s: route.Summary?.DurationSeconds ?? 0,
    }
  } catch {
    return undefined
  }
}
