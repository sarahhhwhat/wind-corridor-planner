// Maps ward code (the "id" property on ward features, e.g. "K/E") to the
// area / locality names covered by that ward.
export const WARD_AREAS = {
  'A': ['Colaba', 'Cuffe Parade', 'Nariman Point', 'Fort', 'Churchgate', 'Navy Nagar'],
  'B': ['Dongri', 'Masjid Bunder', 'Mohammed Ali Road', 'Pydhonie'],
  'C': ['Marine Lines', 'Kalbadevi', 'Bhuleshwar', 'Charni Road', 'Zaveri Bazaar'],
  'D': ['Malabar Hill', 'Grant Road', 'Girgaon', 'Tardeo', 'Breach Candy', 'Walkeshwar', 'Kemps Corner'],
  'E': ['Byculla', 'Mazgaon', 'Agripada', 'Nagpada', 'Mumbai Central'],
  'F/S': ['Parel', 'Lalbaug', 'Sewri', 'Naigaon', 'Bhoiwada'],
  'F/N': ['Matunga', 'Sion', 'Wadala', 'Antop Hill', "King's Circle"],
  'G/S': ['Worli', 'Prabhadevi', 'Lower Parel', 'Elphinstone Road', 'Mahalaxmi'],
  'G/N': ['Dadar', 'Mahim', 'Dharavi', 'Shivaji Park'],
  'H/E': ['Bandra East', 'Bandra Kurla Complex', 'Kalina', 'Vakola', 'Santacruz East', 'Kherwadi'],
  'H/W': ['Bandra West', 'Khar West', 'Santacruz West', 'Pali Hill'],
  'K/E': ['Andheri East', 'Marol', 'MIDC', 'Jogeshwari East', 'Sahar', 'Vile Parle East', 'Chakala'],
  'K/W': ['Andheri West', 'Juhu', 'Versova', 'Vile Parle West', 'Lokhandwala', 'Oshiwara'],
  'P/S': ['Goregaon', 'Aarey Colony', 'Film City', 'Bangur Nagar'],
  'P/N': ['Malad', 'Malvani', 'Mith Chowki', 'Orlem'],
  'R/S': ['Kandivali', 'Charkop', 'Thakur Village', 'Poisar'],
  'R/C': ['Borivali', 'Gorai', 'Eksar', 'Kora Kendra'],
  'R/N': ['Dahisar', 'Anand Nagar'],
  'L': ['Kurla', 'Saki Naka', 'Chandivali', 'Kajupada', 'Asalpha'],
  'M/E': ['Govandi', 'Mankhurd', 'Deonar', 'Trombay', 'Shivaji Nagar'],
  'M/W': ['Chembur', 'Tilak Nagar', 'Chembur Colony', 'Mahul'],
  'N': ['Ghatkopar', 'Vidyavihar', 'Laxmi Nagar', 'Pant Nagar', 'Rajawadi'],
  'S': ['Bhandup', 'Vikhroli', 'Kanjurmarg', 'Powai', 'Nahur'],
  'T': ['Mulund East', 'Mulund West', 'Mulund Colony'],
}

// Safe lookup: returns undefined for unknown ward ids (never throws).
export function wardAreas(id) {
  return WARD_AREAS[id]
}
