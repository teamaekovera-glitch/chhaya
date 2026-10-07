import { useEffect, useRef } from 'react'
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { API_URL, AREA_CENTRE, AWS_REGION, LOCATION_API_KEY } from '../env'
import { DEMO_TILES_STYLE, mapsV2StyleUrl } from './mapStyle'
import {
  clearRouteLines,
  drawRouteLines,
  fitToLines,
  updateEndpoints,
  type EndpointSpec,
  type RouteLine,
} from './draw'

export interface MapViewProps {
  /** Current route overlay — replaced wholesale on change. */
  lines: RouteLine[]
  origin: EndpointSpec['origin']
  destination: EndpointSpec['destination']
  /** Coverage polygon geojson (outside_coverage banner duty; §6.3 shape). */
  coverage?: unknown
}

/** Map + route overlay: Location v2 Standard style centred on Karol Bagh.
 *  Without a key (local dev) it falls back to MapLibre demo tiles and shows a
 *  setup banner. Line drawing lives in `draw.ts`; this component syncs props
 *  into map sources on change. */
export function MapView({ lines, origin, destination, coverage }: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const hasKey = LOCATION_API_KEY !== ''
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: hasKey ? mapsV2StyleUrl(AWS_REGION, LOCATION_API_KEY) : DEMO_TILES_STYLE,
      center: AREA_CENTRE,
      zoom: 14,
      attributionControl: false,
    })
    mapRef.current = map
    map.addControl(new maplibregl.AttributionControl({ compact: true }))
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right')
    // Amazon Location attribution requirement (§7.10).
    map.addControl(
      new maplibregl.AttributionControl({
        customAttribution: '© Amazon Location Service · © OpenStreetMap contributors',
      }),
    )
    map.on('error', (e) => {
      // Style-descriptor 403 almost always means a missing geo-maps:GetStyleDescriptor key action.
      console.error('[chhaya] map error:', e.error?.message ?? e)
    })

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Route lines: replace on every change. Gated on style load — MapLibre
  // throws "Style is not done loading" before the descriptor resolves, so
  // source/layer writes queue until `load`.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!map.isStyleLoaded()) {
      map.once('load', () => {
        clearRouteLines(map)
        drawRouteLines(map, lines)
        const all = lines.flatMap((l) => l.coords)
        if (all.length >= 2) fitToLines(map, all)
      })
      return
    }
    clearRouteLines(map)
    drawRouteLines(map, lines)
    const all = lines.flatMap((l) => l.coords)
    if (all.length >= 2) fitToLines(map, all)
  }, [lines])

  // Endpoint dots — same style-ready gate as the route lines above.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (!map.isStyleLoaded()) {
      map.once('load', () => {
        updateEndpoints(map, { origin, destination })
      })
      return
    }
    updateEndpoints(map, { origin, destination })
  }, [origin, destination])

  // Coverage polygon (outside_coverage banner companion) — outline layer.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !coverage) return
    if (!map.getSource('chhaya-coverage')) {
      map.addSource('chhaya-coverage', {
        type: 'geojson',
        data: coverage as never,
      })
    }
    if (!map.getLayer('chhaya-coverage-line')) {
      map.addLayer({
        id: 'chhaya-coverage-line',
        type: 'line',
        source: 'chhaya-coverage',
        paint: { 'line-color': '#f97316', 'line-width': 2, 'line-dasharray': [2, 2] },
      })
    }
  }, [coverage])

  return (
    <>
      {!LOCATION_API_KEY && (
        <div className="notice">
          Dev mode: MapLibre demo tiles (no <code>VITE_LOCATION_API_KEY</code> set).
          Set it in Amplify env vars — see docs/DEPLOY.md §4.
        </div>
      )}
      {!API_URL && (
        <div className="notice notice--info">
          API not wired yet — Phase 0 skeleton. <code>VITE_API_URL</code> arrives with the backend.
        </div>
      )}
      <div ref={containerRef} className="map" />
    </>
  )
}
