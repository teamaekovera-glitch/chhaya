import { useEffect, useRef } from 'react'
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { API_URL, AREA_CENTRE, AWS_REGION, LOCATION_API_KEY } from '../env'
import { DEMO_TILES_STYLE, mapsV2StyleUrl } from './mapStyle'

/** Phase 0 map: Location v2 Standard style centred on Karol Bagh.
 *  Without a key (local dev) it falls back to MapLibre demo tiles and shows a setup banner. */
export function MapView() {
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
