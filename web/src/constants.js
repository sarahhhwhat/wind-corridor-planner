export const SEASONS = ['winter', 'summer', 'monsoon']

export const SEASON_LABELS = {
  winter: 'Winter (Nov–Feb)',
  summer: 'Summer (Mar–May)',
  monsoon: 'Monsoon (Jun–Sep)',
}

// Ventilation score colour ramp (red = poor, green = good)
const RAMP = [
  [0, '#b91c1c'],
  [0.25, '#ea580c'],
  [0.5, '#facc15'],
  [0.75, '#4ade80'],
  [1, '#15803d'],
]

export function scoreColor(score) {
  if (score == null) return '#64748b'
  const t = Math.max(0, Math.min(1, score / 100))
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const [t0, c0] = RAMP[i - 1]
      const [t1, c1] = RAMP[i]
      const f = (t - t0) / (t1 - t0 || 1)
      return lerpColor(c0, c1, f)
    }
  }
  return RAMP.at(-1)[1]
}

function lerpColor(a, b, f) {
  const pa = hex2rgb(a), pb = hex2rgb(b)
  const p = pa.map((v, i) => Math.round(v + (pb[i] - v) * f))
  return `rgb(${p.join(',')})`
}

function hex2rgb(h) {
  h = h.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16))
}

// NDBI layer colour ramp (blue-ish urban, green-ish open) — values ~[-0.2, +0.2]
export function ndbiColor(v) {
  if (v == null) return 'transparent'
  const t = Math.max(0, Math.min(1, (v + 0.2) / 0.4))
  if (t < 0.5) return lerpColor('#1d4ed8', '#a3e635', t / 0.5)
  return lerpColor('#a3e635', '#b45309', (t - 0.5) / 0.5)
}
