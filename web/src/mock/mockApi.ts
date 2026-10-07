/** ?mock=1 implementation of ChhayaApiLike — DEV/SCREENSHOT ONLY. See mockData.ts. */

import type { CalculateRoutesOptions, PlaceCandidate, RouteRequestBody } from '../api'
import type { BaselineRoute, RouteResponse } from '../types'
import { mockBaseline, mockPlaces, mockRouteResult } from './mockData'

/** Small artificial latency so the loading state is real in recordings. */
function delayed<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms))
}

async function fetchRoute(_apiUrl: string, body: RouteRequestBody): Promise<RouteResponse> {
  return delayed(mockRouteResult(body.mode, body.season, 26))
}

async function searchPlaces(query: string, _apiKey: string, _region: string): Promise<PlaceCandidate[]> {
  return delayed(mockPlaces(query).map((p) => ({ title: p.title, position: p.position })))
}

async function fetchBaselineRoute(_options: CalculateRoutesOptions): Promise<BaselineRoute | undefined> {
  return delayed(mockBaseline())
}

export { fetchRoute, searchPlaces, fetchBaselineRoute }
