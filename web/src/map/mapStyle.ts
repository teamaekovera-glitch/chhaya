/** Amazon Location Maps v2 style descriptor for MapLibre.
 *  Pattern verified against AWS Location docs + decision sheet:
 *  https://maps.geo.{region}.amazonaws.com/v2/styles/{Style}/descriptor
 *    ?color-scheme=Light&variant=Default&key={API_KEY}
 *  Styles: Standard | Monochrome | Hybrid | Satellite. */

export type MapStyle = 'Standard' | 'Monochrome' | 'Hybrid' | 'Satellite'

export function mapsV2StyleUrl(region: string, apiKey: string, style: MapStyle = 'Standard'): string {
  const params = new URLSearchParams({ 'color-scheme': 'Light', variant: 'Default', key: apiKey })
  return `https://maps.geo.${region}.amazonaws.com/v2/styles/${style}/descriptor?${params}`
}

/** Fallback so local dev (no VITE_LOCATION_API_KEY yet) still renders a map. */
export const DEMO_TILES_STYLE = 'https://demotiles.maplibre.org/style.json'
