import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import 'leaflet'
import { scoreColor, ndbiColor, SEASON_LABELS } from './constants.js'
import { wardAreas } from './wardAreas.js'

const MUMBAI = [19.055, 72.90]

export default function MapView({ data, season, layers, selected, onSelect }) {
  const el = useRef(null)
  const map = useRef(null)
  const layerRefs = useRef({})

  // init map once
  useEffect(() => {
    if (map.current || !el.current) return
    map.current = L.map(el.current, { zoomControl: true, preferCanvas: false })
      .setView(MUMBAI, 11)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      maxZoom: 19,
    }).addTo(map.current)
    return () => { map.current?.remove(); map.current = null; layerRefs.current = {} }
  }, [])

  const wardFeatures = useMemo(() => data?.wards ?? [], [data])
  const corridorFeatures = useMemo(() => data?.corridors?.[season]?.features ?? [], [data, season])
  const wind = data?.wind?.seasons?.[season]
  const ndbiGrid = data?.ndbiGrid

  // ward choropleth layer
  useEffect(() => {
    if (!map.current || !wardFeatures.length) return
    if (layerRefs.current.wards) layerRefs.current.wards.remove()
    const geo = { type: 'FeatureCollection', features: wardFeatures }
    const lyr = L.geoJSON(geo, {
      style: (f) => {
        const s = f.properties.seasons?.[season]?.score
        return {
          fillColor: scoreColor(s),
          fillOpacity: 0.55,
          color: '#334155',
          weight: 1,
        }
      },
      onEachFeature: (f, l) => {
        l.on('click', () => onSelect(f.properties))
        l.on('mouseover', () => l.setStyle({ weight: 2.5, color: '#fff' }))
        l.on('mouseout', () => l.setStyle({ weight: 1, color: '#334155' }))
      },
    })
    lyr.addTo(map.current)
    layerRefs.current.wards = lyr
  }, [wardFeatures, season, onSelect])

  // NDBI raster grid (drawn as small rects via canvas-less layer)
  useEffect(() => {
    if (!map.current || !ndbiGrid) return
    if (layerRefs.current.ndbi) layerRefs.current.ndbi.remove()
    const [west, south, east, north] = ndbiGrid.bounds
    const { nrows, ncols, values } = ndbiGrid
    const g = L.layerGroup()
    const latStep = (north - south) / nrows
    const lonStep = (east - west) / ncols
    // opacity per cell proportional to value; only cells with data
    for (let r = 0; r < nrows; r++) {
      for (let c = 0; c < ncols; c++) {
        const v = values[r]?.[c]
        if (v == null) continue
        const lat1 = north - r * latStep
        const lat0 = lat1 - latStep
        const lon0 = west + c * lonStep
        const lon1 = lon0 + lonStep
        // draw sparse: skip every other row/col to limit DOM nodes
        if (r % 2 || c % 2) continue
        L.rectangle([[lat0, lon0], [lat1, lon1]], {
          stroke: false, fillColor: ndbiColor(v), fillOpacity: 0.35, interactive: false,
        }).addTo(g)
      }
    }
    g.addTo(map.current)
    layerRefs.current.ndbi = g
  }, [ndbiGrid])

  // corridor lines
  useEffect(() => {
    if (!map.current) return
    if (layerRefs.current.corridors) layerRefs.current.corridors.remove()
    const g = L.layerGroup()
    corridorFeatures.forEach((f) => {
      L.geoJSON(f, {
        style: () => ({ color: '#0ea5e9', weight: 4 + 2 * (3 - f.properties.rank), opacity: 0.9, dashArray: '8 6' }),
      })
        .bindPopup(
          `<b>Corridor #${f.properties.rank}</b><br/>Wind from ${f.properties.wind} (${f.properties.from_deg}°)` +
          `<br/>Openness: ${f.properties.openness}` +
          `<br/>Wards crossed: ${f.properties.crosses.join(', ')}`
        )
        .addTo(g)
    })
    g.addTo(map.current)
    layerRefs.current.corridors = g
  }, [corridorFeatures])

  // wind arrow overlay (a few arrows along coastal edge pointing TOWARD)
  useEffect(() => {
    if (!map.current || !wind) return
    if (layerRefs.current.arrows) layerRefs.current.arrows.remove()
    const g = L.layerGroup()
    const rad = ((wind.toward_deg) * Math.PI) / 180
    const dx = Math.sin(rad), dy = Math.cos(rad)
    const arrowAt = (lat, lon) => {
      // heading in screen: compass bearing toward
      const size = 26
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      const arrow = L.divIcon({
        className: 'wind-arrow',
        html: `<div style="transform: rotate(${wind.toward_deg}deg); font-size:${size}px; color:#0ea5e9; text-shadow:0 0 3px #000;">➤</div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      })
      L.marker([lat, lon], { icon: arrow, interactive: false }).addTo(g)
    }
    // arrows at coarse fixed grid over Mumbai land
    const pts = [
      [18.93, 72.82], [19.03, 72.83], [19.13, 72.86],
      [18.97, 72.90], [19.10, 72.92],
      [18.92, 72.99], [19.05, 72.97], [19.19, 72.94],
    ]
    pts.forEach(([la, lo]) => arrowAt(la, lo))
    g.addTo(map.current)
    layerRefs.current.arrows = g
  }, [wind])

  // toggle visibility
  useEffect(() => {
    if (!map.current) return
    const refs = layerRefs.current
    if (refs.wards) layers.choropleth ? refs.wards.addTo(map.current) : map.current.removeLayer(refs.wards)
    if (refs.ndbi) layers.ndbi ? refs.ndbi.addTo(map.current) : map.current.removeLayer(refs.ndbi)
    if (refs.corridors) layers.corridors ? refs.corridors.addTo(map.current) : map.current.removeLayer(refs.corridors)
    if (refs.arrows) layers.arrows ? refs.arrows.addTo(map.current) : map.current.removeLayer(refs.arrows)
  }, [layers, wardFeatures, corridorFeatures, ndbiGrid, wind])

  // highlight selected ward via popup-style detail; side panel handles UI
  return (
    <>
      <div id="map" ref={el} />
      {selected && <WardDetail ward={selected} season={season} onClose={() => onSelect(null)} />}
      <WindCard wind={wind} season={season} />
      <Legend layers={layers} />
    </>
  )
}

function WardDetail({ ward, season, onClose }) {
  const s = ward.seasons?.[season]
  const areas = wardAreas(ward.id)
  if (!s) return null
  return (
    <div className="ward-detail">
      <button className="close" onClick={onClose} aria-label="Close">✕</button>
      <h3>{ward.display_name}</h3>
      {areas && (
        <div className="ward-areas">Covers: {areas.join(', ')}</div>
      )}
      <div className="score" style={{ color: scoreColor(s.score) }}>
        {s.score.toFixed(1)} <span style={{ fontSize: '0.75rem', color: 'var(--muted)' }}>/ 100</span>
      </div>
      <div style={{ color: 'var(--muted)', fontSize: '0.75rem', marginBottom: 6 }}>
        Ventilation rank #{s.rank} of 24 · {SEASON_LABELS[season]}
      </div>
      <div><b>NDBI:</b> {ward.ndbi?.toFixed(3) ?? '—'} <span style={{ color: 'var(--muted)' }}>(built-up index)</span></div>
      <div style={{ marginTop: 8 }}><b>Recommendation</b><br />{s.rec}</div>
    </div>
  )
}

function WindCard({ wind, season }) {
  if (!wind) return null
  return (
    <div className="wind-arrow-card">
      <div style={{ color: 'var(--muted)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        Wind blows toward
      </div>
      <div className="arrow" style={{ transform: `rotate(${wind.toward_deg}deg)` }}>➤</div>
      <div><b>{wind.toward_deg}°</b> <span style={{ color: 'var(--muted)' }}>({wind.from_compass} source)</span></div>
      <div style={{ color: 'var(--muted)', fontSize: '0.72rem' }}>
        {SEASON_LABELS[season]} · {wind.mean_speed_ms} m/s mean
      </div>
    </div>
  )
}

function Legend({ layers }) {
  if (!layers.choropleth) return null
  return (
    <div className="legend">
      <div style={{ marginBottom: 4 }}><b>Ventilation score</b></div>
      {[['#15803d', '80–100  excellent'], ['#4ade80', '60–80  good'], ['#facc15', '40–60  fair'], ['#ea580c', '20–40  poor'], ['#b91c1c', '0–20  critical']].map(([c, label]) => (
        <div key={c}><span className="swatch" style={{ background: c }} />{label}</div>
      ))}
      {layers.ndbi && <div style={{ marginTop: 6, fontSize: '0.66rem', color: 'var(--muted)' }}>NDBI overlay: blue = built, amber = open</div>}
      {layers.corridors && <div style={{ marginTop: 2, fontSize: '0.66rem' }}><span className="swatch" style={{ background: 'transparent', borderBottom: '3px dashed #0ea5e9' }} />Ventilation corridor</div>}
    </div>
  )
}
