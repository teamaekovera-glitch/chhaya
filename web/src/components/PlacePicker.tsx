import { useEffect, useState } from 'react'
import type { PlaceCandidate } from '../api'

export type PlaceSelection = {
  title: string
  position: [number, number]
}

export interface PlacePickerProps {
  /** Element id — also drives testids: picker-{id} (origin|destination). */
  id: string
  label: string
  placeholder: string
  selected: PlaceSelection | null
  onSelect: (place: PlaceCandidate) => void
  /** Debounced SearchText call (real Places v2 or mock under ?mock=1). */
  search: (query: string) => Promise<PlaceCandidate[]>
}

const DEBOUNCE_MS = 300

/** Origin/destination picker: debounced, typed, dropdown (§6.7).
 *  Places v2 SearchText returns coordinates in the same call, so one round
 *  trip fills a candidate. The input text is ordinary local state: the parent
 *  keys this component on the selection, so an outside selection change (mock
 *  bootstrap, programmatic pick) remounts it with the title pre-filled and all
 *  transient search state reset — no mirroring effect needed. */
export function PlacePicker({ id, label, placeholder, selected, onSelect, search }: PlacePickerProps) {
  const listId = `${id}-listbox`
  const [query, setQuery] = useState(() => selected?.title ?? '')
  const [results, setResults] = useState<PlaceCandidate[]>([])
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>('idle')

  /** Only freshly typed text is a live search; the selected title and short
   *  input are not. Derived in render — the dropdown hides behind it, so no
   *  effect is needed to clear stale results. */
  const searchable =
    query.trim().length >= 2 && !(selected !== null && query.trim() === selected.title)

  // Debounced SearchText; 300 ms keeps Places call count tiny (credit guardrail).
  // All state writes happen inside the timer's async callback, never in the
  // effect body.
  useEffect(() => {
    const q = query.trim()
    if (!searchable) return
    let cancelled = false
    const timer = setTimeout(() => {
      setStatus('loading')
      search(q)
        .then((res) => {
          if (cancelled) return
          setResults(res)
          setOpen(true)
          setStatus('idle')
        })
        .catch(() => {
          if (cancelled) return
          setResults([])
          setOpen(false)
          setStatus('error')
        })
    }, DEBOUNCE_MS)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [query, searchable, search])

  const choose = (place: PlaceCandidate) => {
    onSelect(place)
    setQuery(place.title)
    setResults([])
    setOpen(false)
    setStatus('idle')
  }

  return (
    <div className={`place-picker place-picker--${id}`}>
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="text"
        className="place-picker__input"
        placeholder={placeholder}
        value={query}
        autoComplete="off"
        role="combobox"
        aria-expanded={open && results.length > 0}
        aria-controls={listId}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => {
          if (results.length > 0) setOpen(true)
        }}
        data-testid={`picker-${id}`}
      />
      {searchable && status === 'loading' && (
        <span className="place-picker__hint" data-testid={`picker-${id}-hint`}>
          Searching…
        </span>
      )}
      {searchable && status === 'error' && (
        <span className="place-picker__hint place-picker__hint--error" role="status">
          Place search is unavailable — no map key or network trouble.
        </span>
      )}
      {searchable && status === 'idle' && results.length === 0 && (
        <span className="place-picker__hint">No matches — try a nearby landmark.</span>
      )}
      {searchable && open && results.length > 0 && (
        <ul id={listId} role="listbox" className="place-picker__listbox" data-testid={`picker-${id}-options`}>
          {results.map((place) => (
            <li key={`${place.placeId ?? place.position[0]},${place.position[1]}`}>
              <button
                type="button"
                role="option"
                aria-selected="false"
                className="place-picker__option"
                onClick={() => choose(place)}
              >
                {place.title}
                {place.addressLabel ? <small>{place.addressLabel}</small> : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
