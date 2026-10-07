import { MapView } from './map/MapView'

/** Phase 0 shell: full-bleed map + a slim title card. Route controls land in Phase 4 (§7.10 UI). */
export default function App() {
  return (
    <div className="app">
      <header className="title-card">
        <h1>छाया · CHHAYA</h1>
        <p>Shade- &amp; flood-aware walking — Karol Bagh, Delhi</p>
      </header>
      <MapView />
    </div>
  )
}
