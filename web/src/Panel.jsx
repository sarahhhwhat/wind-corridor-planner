import { useMemo } from 'react'
import { SEASONS, SEASON_LABELS } from './constants.js'
import { wardAreas } from './wardAreas.js'

const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']

export default function Panel({ season, setSeason, layers, setLayers, data, selected }) {
  const wind = data?.wind?.seasons?.[season]
  const meta = data?.wind?.meta

  const wardScores = useMemo(() => {
    if (!data?.wards) return []
    return data.wards
      .map((f) => ({ id: f.properties.id, name: f.properties.display_name, score: f.properties.seasons?.[season]?.score ?? 0, rec: f.properties.seasons?.[season]?.rec }))
      .filter((w) => w.score != null)
      .sort((a, b) => b.score - a.score)
  }, [data, season])

  return (
    <aside className="panel">
      <h1>Mumbai Wind Corridor Planner</h1>
      <p className="intro">
        Where urban ventilation corridors should be protected or created in Mumbai, based on seasonal
        prevailing wind (2020–2025, Open-Meteo) and satellite-derived built-up density (Sentinel-2 NDBI).
      </p>

      <div className="season-tabs">
        {SEASONS.map((s) => (
          <button key={s} className={s === season ? 'active' : ''} onClick={() => setSeason(s)}>
            {s[0].toUpperCase() + s.slice(1)}
          </button>
        ))}
      </div>

      {wind && (
        <>
          <div className="wind-summary">
            <div className="big">{wind.from_compass} · {wind.from_deg}°</div>
            <div className="sub">prevailing FROM-direction, {SEASON_LABELS[season]} · mean {wind.mean_speed_ms} m/s</div>
          </div>
          <WindRose rose={wind.rose} fromDeg={wind.from_deg} />
        </>
      )}

      <div className="section-title">Layers</div>
      <div className="toggles">
        <Toggle k="choropleth" label="Ventilation score" layers={layers} setLayers={setLayers} />
        <Toggle k="ndbi" label="NDBI (built-up)" layers={layers} setLayers={setLayers} />
        <Toggle k="corridors" label="Corridor lines" layers={layers} setLayers={setLayers} />
        <Toggle k="arrows" label="Wind arrows" layers={layers} setLayers={setLayers} />
      </div>

      <div className="section-title">Top 5 best ventilated</div>
      <WardsTable rows={wardScores.slice(0, 5)} />
      <div className="section-title">Top 5 worst ventilated</div>
      <WardsTable rows={[...wardScores].slice(-5).reverse()} />

      <div className="section-title">How it works</div>
      <div className="how">
        Prevailing wind per season is the speed-weighted vector mean of hourly Open-Meteo ERA5 winds
        (2020–01-01 → 2025-12-31). Built-up density is the mean Sentinel-2 NDBI per ward (dry-season
        composite, cloud &lt; 10 %). The ventilation score blends (1 − built-up) with wind exposure:
        wards nearer the upwind edge get more unobstructed fetch than sheltered inland wards. Corridor
        lines run along the seasonal wind bearing, ranked by how little built-up they cross. Scores are
        comparative inside Mumbai, not absolute measurements.
      </div>
      {meta && (
        <div style={{ marginTop: 6, fontSize: '0.68rem', color: 'var(--muted)' }}>
          Wind: {meta.source}, {meta.period}. October excluded (weak transition month).
        </div>
      )}

      {data?.ndbiMeta && (
        <footer className="attrib">
          Sources: ward map © BMC; wind data <a href="https://open-meteo.com/">Open-Meteo</a> (CC BY 4.0);
          Sentinel-2 imagery via <a href="https://planetarycomputer.microsoft.com/">Microsoft Planetary Computer</a>;
          basemap © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, ©
          <a href="https://carto.com/attributions"> CARTO</a>. Built for planning discussion, not a substitute for detailed CFD studies.
        </footer>
      )}
      {!data?.ndbiMeta && (
        <footer className="attrib">
          Sources: wind data <a href="https://open-meteo.com/">Open-Meteo</a>; basemap ©
          <a href="https://www.openstreetmap.org/copyright"> OpenStreetMap</a> contributors,
          <a href="https://carto.com/attributions"> CARTO</a>.
        </footer>
      )}
    </aside>
  )
}

function Toggle({ k, label, layers, setLayers }) {
  return (
    <label>
      <input type="checkbox" checked={!!layers[k]} onChange={(e) => setLayers((L) => ({ ...L, [k]: e.target.checked }))} />
      {label}
    </label>
  )
}

function WardsTable({ rows }) {
  if (!rows.length) return null
  return (
    <table className="wards-table">
      <tbody>
        {rows.map((w) => {
          const areas = wardAreas(w.id)
          const short = areas?.slice(0, 3)
          return (
            <tr key={w.id}>
              <td>
                {w.name}
                {short?.length > 0 && (
                  <div className="ward-areas-short" title={areas.join(', ')}>
                    {short.join(', ')}{areas.length > 3 ? '…' : ''}
                  </div>
                )}
              </td>
              <td className="num">{w.score.toFixed(1)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function WindRose({ rose, fromDeg }) {
  const size = 170, cx = size / 2, cy = size / 2, R = 70
  const max = Math.max(...Object.values(rose), 1)
  const sectors = COMPASS.map((label, i) => {
    const v = rose[label] ?? 0
    const r = (v / max) * R
    const a0 = ((i * 22.5 - 11.25 - 90) * Math.PI) / 180
    const a1 = ((i * 22.5 + 11.25 - 90) * Math.PI) / 180
    const x0 = cx + r * Math.cos(a0), y0 = cy + r * Math.sin(a0)
    const x1 = cx + r * Math.cos(a1), y1 = cy + r * Math.sin(a1)
    const x2 = cx, y2 = cy
    return { d: `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1} L ${x2} ${y2} Z`, v, label }
  })
  // prevailing FROM arrow (points into the wind = toward the source)
  const pa = ((fromDeg - 90) * Math.PI) / 180
  return (
    <div className="rose">
      <svg width={size} height={size} role="img" aria-label="Wind rose">
        <circle cx={cx} cy={cy} r={R} fill="none" stroke="#2a3a5f" />
        <circle cx={cx} cy={cy} r={R / 2} fill="none" stroke="#2a3a5f" strokeDasharray="3 3" />
        <text x={cx} y={10} fontSize="9" fill="#9fb0c9" textAnchor="middle">N</text>
        <text x={cx} y={size - 3} fontSize="9" fill="#9fb0c9" textAnchor="middle">S</text>
        <text x={6} y={cy + 3} fontSize="9" fill="#9fb0c9" textAnchor="middle">W</text>
        <text x={size - 6} y={cy + 3} fontSize="9" fill="#9fb0c9" textAnchor="middle">E</text>
        {sectors.map((s, i) => (
          <path key={s.label} d={s.d} fill="#38bdf8" fillOpacity={0.15 + 0.6 * (s.v / max)} stroke="#38bdf8" strokeOpacity={0.5} />
        ))}
        <line x1={cx} y1={cy} x2={cx + R * Math.cos(pa - Math.PI / 2)} y2={cy + R * Math.sin(pa - Math.PI / 2)}
          stroke="#f59e0b" strokeWidth={2} markerEnd="url(#arrow)" />
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" fill="#f59e0b" />
          </marker>
        </defs>
        <text x={cx} y={cy - 6} fontSize="9" fill="#f59e0b" textAnchor="middle">prevailing</text>
      </svg>
    </div>
  )
}
