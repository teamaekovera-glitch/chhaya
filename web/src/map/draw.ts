/** Route-line drawing on MapLibre — pure map plumbing, no React state.
 *
 *  Layer order (z): baseline first (bottom), then chhaya, then direct on top,
 *  so the direct line never hides the route being showcased.
 */

import type { Map as MapLibreMap } from 'maplibre-gl'
import type { Season } from '../types'

export interface RouteLine {
  /** Source + layer id (plain, no prefix). */
  id: string
  coords: [number, number][]
  color: string
  width: number
  dashed?: boolean
}

export interface EndpointSpec {
  origin: [number, number] | undefined
  destination: [number, number] | undefined
}

type Coords = [number, number][]

interface PointGeometry {
  type: 'Point'
  coordinates: [number, number]
}

interface LineGeometry {
  type: 'LineString'
  coordinates: Coords
}

interface GeoFeature {
  type: 'Feature'
  properties: Record<string, never>
  geometry: PointGeometry | LineGeometry
}

interface MapLibreGeoJsonSource {
  setData(data: GeoFeature): void
}

function lineFeature(coords: Coords): GeoFeature {
  return { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }
}

function pointFeature(coords: [number, number]): GeoFeature {
  return { type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: coords } }
}

/** Adds (once) source+layer for each line and pushes current coords.
 *  Plain lines only — the §7.10 line-gradient styling is a nice-to-have. */
export function drawRouteLines(map: MapLibreMap, lines: RouteLine[]): void {
  for (const line of lines) {
    if (!line.coords || line.coords.length < 2) continue
    const sourceId = `chhaya-${line.id}`
    const layerId = `${sourceId}-line`
    const feature = lineFeature(line.coords)

    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: 'geojson', data: feature })
    } else {
      const src = map.getSource(sourceId) as unknown
      if (src && typeof (src as MapLibreGeoJsonSource).setData === 'function') {
        ;(src as MapLibreGeoJsonSource).setData(feature)
      }
    }
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': line.color,
          'line-width': line.width,
          ...(line.dashed ? { 'line-dasharray': [1.5, 1.5] } : {}),
        },
      })
    }
    // Paint is fixed at layer creation — a season switch (summer→monsoon)
    // must update paint or the map silently keeps the old palette.
    if (map.getLayer(layerId)) {
      map.setPaintProperty(layerId, 'line-color', line.color)
      map.setPaintProperty(layerId, 'line-width', line.width)
    }
  }
}

const ROUTE_IDS = ['baseline', 'direct', 'chhaya'] as const
const POINT_IDS = ['pt-origin', 'pt-destination'] as const

/** Removes every route + endpoint source/layer. */
export function clearRouteLines(map: MapLibreMap): void {
  for (const id of [...ROUTE_IDS, ...POINT_IDS]) {
    const layerId = `${id}-line`
    if (map.getLayer(layerId)) map.removeLayer(layerId)
    if (map.getSource(id)) map.removeSource(id)
  }
}

/** Endpoint dots (origin/destination) — undefined entries are skipped so a
 *  half-filled form keeps the last known dot instead of erroring. */
export function updateEndpoints(map: MapLibreMap, spec: EndpointSpec): void {
  const pairs: Array<[string, [number, number] | undefined]> = [
    ['pt-origin', spec.origin],
    ['pt-destination', spec.destination],
  ]
  for (const [id, coords] of pairs) {
    if (!coords) continue
    const feature = pointFeature(coords)
    if (!map.getSource(id)) {
      map.addSource(id, { type: 'geojson', data: feature })
    } else {
      const src = map.getSource(id) as unknown
      if (src && typeof (src as MapLibreGeoJsonSource).setData === 'function') {
        ;(src as MapLibreGeoJsonSource).setData(feature)
      }
    }
    if (!map.getLayer(`${id}-line`)) {
      map.addLayer({
        id: `${id}-line`,
        type: 'circle',
        source: id,
        paint: {
          'circle-radius': 7,
          'circle-color': '#1c1917',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#fffefb',
        },
      })
    }
  }
}

/** Contrast palette per §10 brief: direct gray, chhaya cool green (summer) /
 *  warm blue (monsoon), baseline light gray dashed. */
export function chhayaColor(season: Season): string {
  return season === 'summer' ? '#0d9488' : '#2563eb'
}

export const DIRECT_COLOR = '#a8a29e'
export const BASELINE_COLOR = '#d6d3d1'

/** Fits the map to the given coordinate envelope with padding. */
export function fitToLines(map: MapLibreMap, coords: Coords): void {
  if (coords.length < 2) return
  let west = Infinity
  let east = -Infinity
  let south = Infinity
  let north = -Infinity
  for (const [x, y] of coords) {
    west = Math.min(west, x)
    east = Math.max(east, x)
    south = Math.min(south, y)
    north = Math.max(north, y)
  }
  map.fitBounds(
    [
      [west, south],
      [east, north],
    ],
    { padding: 64, maxZoom: 16, duration: 350, linear: true },
  )
}
