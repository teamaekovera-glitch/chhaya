import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, IS_MOCK, type ChhayaApiLike } from './runtime'
import { API_URL, AWS_REGION, LOCATION_API_KEY } from './env'
import { PlacePicker, type PlaceSelection } from './components/PlacePicker'
import { TimeStrip } from './components/TimeStrip'
import { ChipRow, Legend, type Chip } from './components/Chips'
import { BASELINE_COLOR, DIRECT_COLOR, chhayaColor, type RouteLine } from './map/draw'
import { MapView } from './map/MapView'
import { isApiError, type Mode, type RouteResponse, type RouteResult, type Season } from './types'
import { formatDelta, formatDistance, formatDuration, formatFlood, formatShade } from './format'
import { slotTimeLabel } from './timeSlots'
import {
  MOCK_DESTINATION,
  MOCK_DESTINATION_NAME,
  MOCK_ORIGIN,
  MOCK_ORIGIN_NAME,
} from './mock/mockData'

/** Default departure: 13:30 IST (slot index 26 — 07:00 + 26·15 min).
 *  The brief's '(24, 13:30)' is internally off by one; the visible IST label
 *  13:30 is what the backend contract ties to slot 26 (07:00 + i·15). */
const DEFAULT_SLOT = 26

const MODE_ROW: Array<{ key: Mode; label: string; hint: string }> = [
  { key: 'direct', label: 'Direct', hint: 'shortest walk' },
  { key: 'shade', label: 'Chhaya ☀', hint: 'cooler walk (summer)' },
  { key: 'flood', label: 'Chhaya 🌧', hint: 'keep dry (monsoon)' },
]

type Banner = { kind: 'info' | 'error'; text: string } | null

export default function App() {
  // ?mock=1 boots with the Karol Bagh preset already picked (lazy init — no
  // bootstrap effect), so the auto-run below has endpoints on first render.
  const [origin, setOrigin] = useState<PlaceSelection | null>(() =>
    IS_MOCK ? { title: MOCK_ORIGIN_NAME, position: MOCK_ORIGIN } : null,
  )
  const [destination, setDestination] = useState<PlaceSelection | null>(() =>
    IS_MOCK ? { title: MOCK_DESTINATION_NAME, position: MOCK_DESTINATION } : null,
  )
  const [slotIndex, setSlotIndex] = useState(DEFAULT_SLOT)
  const [season, setSeason] = useState<Season>('summer')
  const [mode, setMode] = useState<Mode>('shade')
  const [directResult, setDirectResult] = useState<RouteResult | null>(null)
  const [optimizedResult, setOptimizedResult] = useState<RouteResult | null>(null)
  const [baseline, setBaseline] = useState<Awaited<ReturnType<ChhayaApiLike['fetchBaselineRoute']>>>(undefined)
  const [loading, setLoading] = useState(false)
  const [banner, setBanner] = useState<Banner>(null)

  const hasFetched = useRef(false)
  const runRef = useRef<() => void>(undefined)

  const searchPlacesFn = useCallback(
    (query: string) => api.searchPlaces(query, LOCATION_API_KEY, AWS_REGION),
    [],
  )

  /** Season switch maps the optimized mode (brief §10a): summer → shade,
   *  monsoon → flood. */
  const handleSeason = (next: Season) => {
    setSeason(next)
    setMode(next === 'summer' ? 'shade' : 'flood')
  }

  /** Selection handlers — PlaceSelection is the pickers' narrow type. */
  const handleOriginSelect = (place: PlaceSelection) => setOrigin(place)
  const handleDestinationSelect = (place: PlaceSelection) => setDestination(place)

  const findRoutes = useCallback(() => {
    const originPos = origin?.position
    const destPos = destination?.position
    if (!originPos || !destPos) {
      setBanner({ kind: 'info', text: 'Pick an origin and a destination first.' })
      return
    }
    if (!IS_MOCK && !API_URL) {
      setBanner({ kind: 'error', text: 'Backend URL not configured (VITE_API_URL).' })
      return
    }
    setLoading(true)
    setBanner(null)
    const time = slotTimeLabel(slotIndex)
    const body = { origin: originPos, destination: destPos, time }
    const posts: Array<Promise<RouteResponse>> = mode === 'direct'
      ? [api.fetchRoute(API_URL, { ...body, mode: 'direct', season })]
      : [
          api.fetchRoute(API_URL, { ...body, mode: 'direct', season }),
          api.fetchRoute(API_URL, { ...body, mode, season }),
        ]
    Promise.all(posts)
      .then(([directRes, optRes]) => {
        setDirectResult('route' in directRes ? directRes : null)
        setOptimizedResult(optRes && 'route' in optRes ? optRes : null)
        const anyError = [directRes, optRes].find((r) => r && isApiError(r))
        if (anyError && isApiError(anyError)) {
          setBanner({ kind: bannerFor(anyError), text: bannerText(anyError) })
        }
        // Baseline never gates the route (§6.5): fail silently absent.
        api
          .fetchBaselineRoute({ origin: originPos, destination: destPos, apiKey: LOCATION_API_KEY, region: AWS_REGION })
          .then((res) => setBaseline(res))
      })
      .catch(() => {
        setBanner({ kind: 'error', text: 'Route service unreachable — the map and place search still work.' })
      })
      .finally(() => setLoading(false))
    hasFetched.current = true
  }, [origin, destination, slotIndex, season, mode])

  // Keep the latest runnable for debounced refetch after input changes.
  useEffect(() => {
    runRef.current = findRoutes
  })

  // Auto-run once in mock mode so the screenshot/QA loop has content.
  useEffect(() => {
    if (!IS_MOCK || hasFetched.current || !origin || !destination) return
    const run = runRef.current
    if (run) run()
  }, [origin, destination])

  // Debounced refetch on slot / season / endpoint edits, after a run exists.
  useEffect(() => {
    if (!hasFetched.current || !origin || !destination) return
    const run = runRef.current
    if (!run) return
    const t = setTimeout(run, 400)
    return () => clearTimeout(t)
  }, [season, slotIndex, origin, destination])

  const lines: RouteLine[] = useMemo(() => {
    const out: RouteLine[] = []
    if (baseline) {
      out.push({ id: 'baseline', coords: baseline.geometry, color: BASELINE_COLOR, width: 3, dashed: true })
    }
    if (directResult) {
      out.push({ id: 'direct', coords: directResult.route, color: DIRECT_COLOR, width: 4 })
    }
    if (optimizedResult && mode !== 'direct') {
      out.push({
        id: 'chhaya',
        coords: optimizedResult.route,
        color: chhayaColor(optimizedResult.season),
        width: 5,
      })
    }
    return out
  }, [baseline, directResult, optimizedResult, mode])

  const chips = useMemo<Chip[]>(() => {
    const out: Chip[] = []
    if (mode !== 'direct' && optimizedResult) {
      if (directResult) {
        const dt = optimizedResult.duration_s - directResult.duration_s
        const dm = optimizedResult.distance_m - directResult.distance_m
        const delta = formatDelta(dt, dm)
        if (delta) out.push({ label: 'vs direct', value: delta, tone: dt > 90 ? 'warn' : 'neutral' })
      }
      out.push({
        label: 'Shade',
        value: formatShade(optimizedResult.shade_score),
        tone: optimizedResult.shade_score >= 0.5 ? 'good' : 'neutral',
      })
      const flood = formatFlood(optimizedResult.flood_profile.monsoon)
      if (flood) out.push({ label: 'Flood', value: flood, tone: 'neutral' })
    } else if (directResult) {
      const flood = formatFlood(directResult.flood_profile.monsoon)
      if (flood) out.push({ label: 'Flood', value: flood, tone: 'neutral' })
    }
    if (baseline) {
      out.push({ label: 'Baseline', value: `${formatDistance(baseline.distance_m)} · ${formatDuration(baseline.duration_s)}` })
    }
    return out
  }, [mode, directResult, optimizedResult, baseline])

  /** Sparkline = shade_profile (§6.7). The contract carries no per-slot flood
   *  series (flood_profile is a scalar pair), so the curve is drawn only when
   *  shade is what the mode routes on — omitted in monsoon. */
  const profileForStrip = useMemo(
    () =>
      mode !== 'direct' && optimizedResult
        ? season === 'summer'
          ? optimizedResult.shade_profile
          : undefined
        : season === 'summer'
          ? directResult?.shade_profile
          : undefined,
    [mode, season, optimizedResult, directResult],
  )

  return (
    <div className="app">
      <header className="title-card">
        <h1>छाया · CHHAYA</h1>
        <p>Shade- &amp; flood-aware walking — Karol Bagh, Delhi</p>
      </header>

      <MapView lines={lines} origin={origin?.position} destination={destination?.position} />

      <section className="route-card" aria-live="polite">
        {/* Keyed on the selection: an outside pick (mock bootstrap, future
            programmatic set) remounts the picker with fresh text. */}
        <PlacePicker
          key={origin?.title ?? 'origin-unpicked'}
          id="origin"
          label="From"
          placeholder="e.g. Karol Bagh Metro Station"
          selected={origin}
          onSelect={handleOriginSelect}
          search={searchPlacesFn}
        />
        <PlacePicker
          key={destination?.title ?? 'destination-unpicked'}
          id="destination"
          label="To"
          placeholder="e.g. Ajmal Khan Park"
          selected={destination}
          onSelect={handleDestinationSelect}
          search={searchPlacesFn}
        />

        <div className="season-toggle" role="group" aria-label="Season">
          <button
            type="button"
            className={`season season--summer${season === 'summer' ? ' season--active' : ''}`}
            aria-pressed={season === 'summer'}
            onClick={() => handleSeason('summer')}
            data-testid="season-summer"
          >
            Summer ☀
          </button>
          <button
            type="button"
            className={`season season--monsoon${season === 'monsoon' ? ' season--active' : ''}`}
            aria-pressed={season === 'monsoon'}
            onClick={() => handleSeason('monsoon')}
            data-testid="season-monsoon"
          >
            Monsoon 🌧
          </button>
        </div>

        <div className="mode-row" role="group" aria-label="Route mode">
          {MODE_ROW.map((entry) => (
            <button
              key={entry.key}
              type="button"
              className={`mode mode--${entry.key}${mode === entry.key ? ' mode--active' : ''}`}
              aria-pressed={mode === entry.key}
              title={entry.hint}
              onClick={() => setMode(entry.key)}
              data-testid={`mode-${entry.key}`}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <button type="button" className="find" onClick={findRoutes} disabled={loading} data-testid="find-routes">
          {loading ? 'Finding…' : 'Find route'}
        </button>

        {loading && <div className="statusline" data-testid="loading">Finding routes…</div>}
        {banner && (
          <div className={`banner banner--${banner.kind}`} role="status" data-testid="banner">
            {banner.text}
          </div>
        )}

        <ChipRow chips={chips} />

        <TimeStrip selected={slotIndex} onSelect={setSlotIndex} disabled={loading} shadeProfile={profileForStrip} />

        <Legend season={season} />
      </section>
    </div>
  )
}

function bannerFor(res: { error: string }): 'error' | 'info' {
  return res.error === 'outside_coverage' ? 'info' : 'error'
}

function bannerText(res: { error: string; detail?: string }): string {
  switch (res.error) {
    case 'outside_coverage':
      return 'That point is outside the Karol Bagh coverage area — pick nearby streets.'
    case 'no_route':
      return 'No walking route connects those points right now.'
    case 'bad_request':
      return `Routing rejected the request: ${res.detail ?? 'check origin and destination.'}`
    default:
      return 'Route service is having trouble — try again shortly.'
  }
}
