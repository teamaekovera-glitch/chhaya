/** Runtime API selector — the only import surface App uses for remote calls.
 *
 *  ?mock=1 swaps a fully mock `ChhayaApiLike` implementation (DEV/SCREENSHOT
 *  ONLY: no AWS credentials / no Location key in this environment). Without
 *  the flag everything is live: fetchRoute against VITE_API_URL, Places
 *  SearchText + CalculateRoutes against Location v2 with the key.
 */

import type { CalculateRoutesOptions, PlaceCandidate, RouteRequestBody } from './api'
import type { BaselineRoute, RouteResponse } from './types'

/** The API surface App consumes; implemented by api.ts (live) or mockApi.ts. */
export interface ChhayaApiLike {
  fetchRoute(apiUrl: string, body: RouteRequestBody): Promise<RouteResponse>
  searchPlaces(query: string, apiKey: string, region: string): Promise<PlaceCandidate[]>
  fetchBaselineRoute(options: CalculateRoutesOptions): Promise<BaselineRoute | undefined>
}

import * as live from './api'
import * as mock from './mock/mockApi'

export type ApiImpl = typeof live

export function makeApi(search: string): ApiImpl {
  const isMock = new URLSearchParams(search).get('mock') === '1'
  return isMock ? (mock as ApiImpl) : live
}

export const api: ChhayaApiLike = makeApi(window.location.search)

export const IS_MOCK = new URLSearchParams(window.location.search).get('mock') === '1'
