import { useEffect, useState } from 'react'
import MapView from './MapView.jsx'
import Panel from './Panel.jsx'
import { SEASONS } from './constants.js'

const DATA = (p) => `${import.meta.env.BASE_URL}data/${p}`

async function fetchJson(name) {
  const r = await fetch(DATA(name))
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`)
  return r.json()
}

export default function App() {
  const [season, setSeason] = useState('winter')
  const [layers, setLayers] = useState({ wardLayer: 'priority', ndbi: false, corridors: true, arrows: true })
  const [selected, setSelected] = useState(null)     // ward props or null
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)             // {wards, wind, ndbi, corridors}

  useEffect(() => {
    let on = true
    ;(async () => {
      try {
        const [wards, wind] = await Promise.all([fetchJson('wards.geojson'), fetchJson('wind_seasons.json')])
        let ndbiMeta = null
        let ndbiGrid = null
        try { ndbiMeta = await fetchJson('ndbi.json') } catch { /* optional */ }
        try { ndbiGrid = await fetchJson('ndbi_raster_4326.json') } catch { /* optional */ }
        const corridors = {}
        for (const s of SEASONS) {
          corridors[s] = await fetchJson(`corridors_${s}.geojson`)
        }
        if (!on) return
        setData({ wards: wards.features, wind, ndbiMeta, ndbiGrid, corridors })
      } catch (e) {
        if (on) setError(`Failed to load map data. ${e.message}`)
      } finally {
        if (on) setLoading(false)
      }
    })()
    return () => { on = false }
  }, [])

  if (error) {
    return (
      <div className="app">
        <div className="state-card error">
          <div>⚠️ {error}</div>
          <div style={{fontSize:'0.8rem', color:'var(--muted)'}}>Try reloading the page.</div>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <Panel season={season} setSeason={setSeason} layers={layers} setLayers={setLayers} data={data} selected={selected} />
      <div className="map-wrap">
        {loading && (
          <div className="state-card">
            <div className="spinner" />
            <div>Loading Mumbai wind data…</div>
          </div>
        )}
        {data && (
          <MapView data={data} season={season} layers={layers} selected={selected} onSelect={(p) => setSelected(p)} />
        )}
      </div>
    </div>
  )
}
