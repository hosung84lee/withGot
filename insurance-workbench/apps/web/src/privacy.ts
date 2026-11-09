export const treatmentNames = {
  consultation: '외래 진찰료',
  blood_test: '혈액 검사',
  mri: '복부 MRI',
  injection: '영양 주사',
} as const

export type TreatmentKind = keyof typeof treatmentNames
export type Benefit = 'covered' | 'uncovered' | 'unknown'
export type Enrollment = 'enrolled' | 'not_enrolled' | 'unknown'
export type Contract = Record<'standard' | 'mri' | 'injection', Enrollment>
export const benefitNames: Record<Benefit, string> = {
  covered: '급여', uncovered: '비급여', unknown: '미확인',
}
export const coverageNames = { standard: '질병급여', mri: '비급여 MRI', injection: '비급여 주사' }
export const enrollmentNames: Record<Enrollment, string> = {
  enrolled: '가입', not_enrolled: '미가입', unknown: '미확인',
}

export interface SourceLine {
  text: string
  page: number
  left: number
  top: number
  width: number
  height: number
}

export interface SourcePage {
  url: string
  width: number
  height: number
  lines: SourceLine[]
}

export interface LocalDocument {
  name: string
  pages: SourcePage[]
}

export function releaseDocuments(documents: LocalDocument[]) {
  for (const document of documents) {
    for (const page of document.pages) URL.revokeObjectURL(page.url)
  }
}

export interface ReviewItem {
  kind: TreatmentKind | 'unknown'
  benefit: Benefit
  total: string
  patient: string
  selected: boolean
  document: number
  source: SourceLine
  original: string
  extracted: { kind: TreatmentKind | 'unknown'; benefit: Benefit; total: string; patient: string }
}

export interface ParsedPair {
  items: ReviewItem[]
  patientTotal: number
  caseId: string
  receiptIndex: number
}

const MAX_MONEY = 100_000_000

export function moneyValue(value: string): number | null {
  if (!/^\d{1,9}$/.test(value)) return null
  const amount = Number(value)
  return amount <= MAX_MONEY ? amount : null
}

export function parsePair(documents: LocalDocument[]): ParsedPair {
  if (documents.length !== 2) throw new Error('영수증과 세부내역서 PDF를 함께 선택해 주세요.')
  const allLines = documents.map(document => document.pages.flatMap(page => page.lines))
  const receiptMarker = 'BOJANGIT SAMPLE V1 RECEIPT'
  const detailMarker = 'BOJANGIT SAMPLE V1 DETAIL'
  const markers = allLines.map(lines => lines.filter(line => line.text === receiptMarker || line.text === detailMarker))
  const receiptIndex = markers.findIndex(lines => lines.length === 1 && lines[0].text === receiptMarker)
  const detailIndex = markers.findIndex(lines => lines.length === 1 && lines[0].text === detailMarker)
  if (receiptIndex < 0 || detailIndex < 0) {
    throw new Error('지원하는 가상 영수증·세부내역서 한 쌍이 필요합니다. 아래 샘플 PDF로 시작해 주세요.')
  }
  function field(lines: SourceLine[], label: string) {
    const matches = lines.filter(line => line.text.startsWith(label + ' | '))
    if (matches.length !== 1) throw new Error('서류의 필수 항목을 확인할 수 없습니다.')
    return matches[0].text.slice(label.length + 3).trim()
  }
  const receipt = allLines[receiptIndex]
  const detail = allLines[detailIndex]
  const caseId = field(receipt, '사례번호')
  if (!caseId || caseId !== field(detail, '사례번호')) {
    throw new Error('서로 다른 사례의 서류입니다. 같은 진료 건의 두 PDF를 선택해 주세요.')
  }
  const patientTotal = moneyValue(field(receipt, '환자 부담 합계'))
  if (patientTotal === null) throw new Error('영수증 환자 부담 합계를 확인할 수 없습니다.')
  const items: ReviewItem[] = []
  for (const line of detail) {
    if (!line.text.startsWith('치료 | ')) continue
    const fields = line.text.split('|').map(field => field.trim())
    if (fields.length !== 5 || moneyValue(fields[3]) === null || moneyValue(fields[4]) === null) {
      throw new Error('세부내역서에 읽을 수 없는 치료 행이 있습니다. 지원 서식을 확인해 주세요.')
    }
    const kind = (Object.keys(treatmentNames) as TreatmentKind[])
      .find(key => treatmentNames[key] === fields[1]) ?? 'unknown'
    const benefit = (Object.keys(benefitNames) as Benefit[])
      .find(key => benefitNames[key] === fields[2]) ?? 'unknown'
    items.push({ kind, benefit, total: fields[3], patient: fields[4], selected: kind !== 'unknown',
      document: detailIndex, source: line, original: line.text,
      extracted: { kind, benefit, total: fields[3], patient: fields[4] } })
  }
  const count = field(detail, '항목 수')
  if (!/^\d{1,3}$/.test(count) || Number(count) !== items.length || !items.length || items.length > 100) {
    throw new Error('치료 항목 수가 맞지 않습니다. 누락된 행을 확인해 주세요.')
  }
  return { items, patientTotal, caseId, receiptIndex }
}

export interface TransferItem {
  item_id: number
  kind: TreatmentKind
  benefit: Benefit
}

export interface Transfer {
  rule_version: 'synthetic-v1'
  contract: Partial<Contract>
  items: TransferItem[]
}

export interface Candidate {
  item_id: number
  coverage: keyof typeof coverageNames
  status: 'candidate' | 'missing_information' | 'not_enrolled'
  checks: string[]
}

export function selectedCoverages(items: ReviewItem[]): Set<keyof Contract> {
  const keys = new Set<keyof Contract>()
  for (const item of items) {
    if (!item.selected || item.kind === 'unknown' || item.benefit === 'unknown') continue
    if (item.benefit === 'uncovered' && (item.kind === 'mri' || item.kind === 'injection')) {
      keys.add(item.kind)
    } else {
      keys.add('standard')
    }
  }
  return keys
}

export function transferSnapshot(items: ReviewItem[], contract: Contract): string {
  const selected = items.flatMap((item, index) => {
    if (!item.selected) return []
    if (item.kind === 'unknown') {
      throw new Error('선택한 항목의 치료 종류를 확인해 주세요.')
    }
    return [{ item_id: index + 1, kind: item.kind, benefit: item.benefit }]
  })
  if (!selected.length) throw new Error('조회할 치료 항목을 하나 이상 선택해 주세요.')
  // Construct the allowlist explicitly. Local source objects never enter this object.
  const required = selectedCoverages(items)
  const relevantContract: Partial<Contract> = {}
  for (const key of Object.keys(coverageNames) as (keyof Contract)[]) {
    if (required.has(key)) relevantContract[key] = contract[key]
  }
  const transfer: Transfer = {
    rule_version: 'synthetic-v1',
    contract: relevantContract,
    items: selected,
  }
  return JSON.stringify(transfer, null, 2)
}

export function isCandidateResponse(value: unknown, expected: Transfer): value is {
  rule_version: 'synthetic-v1'; synthetic: true; items: Candidate[]
} {
  if (!value || typeof value !== 'object') return false
  const response = value as { rule_version?: unknown; synthetic?: unknown; items?: unknown }
  if (response.rule_version !== expected.rule_version || response.synthetic !== true || !Array.isArray(response.items)) return false
  if (response.items.length !== expected.items.length) return false
  return response.items.every((item, index) => item && item.item_id === expected.items[index].item_id
    && Object.hasOwn(coverageNames, item.coverage)
    && ['candidate', 'missing_information', 'not_enrolled'].includes(item.status)
    && Array.isArray(item.checks) && item.checks.every((check: unknown) => typeof check === 'string'))
}
