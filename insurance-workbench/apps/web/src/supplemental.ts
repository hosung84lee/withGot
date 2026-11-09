import { moneyValue } from './privacy'
import type { LocalDocument, ReviewItem } from './privacy'

export const documentKinds = {
  DIAGNOSIS: '진단서', PRESCRIPTION: '처방전', PAYMENT: '납입확인서', PHARMACY: '약제비 영수증',
} as const

type Evidence<T> = { value: T; page: number; text: string }
type Base = { name: string; id: string }
export type SupportingDocument = Base & (
  | { kind: 'DIAGNOSIS'; diagnosis: Evidence<string>; code?: Evidence<string> }
  | { kind: 'PRESCRIPTION'; medications: Evidence<{ name: string; days: number }>[] }
  | { kind: 'PAYMENT'; paid: Evidence<number> }
  | { kind: 'PHARMACY'; prescriptionId: Evidence<string>; covered: Evidence<number>;
      uncovered: Evidence<number>; paid: Evidence<number> }
)
export type PaymentRelation = 'separate' | 'included'

export function parseSupportingDocument(document: LocalDocument, caseId: string): SupportingDocument {
  const lines = document.pages.flatMap(page => page.lines)
  const markers = lines.filter(line => line.text.startsWith('BOJANGIT SAMPLE V1 '))
  const kind = markers[0]?.text.slice('BOJANGIT SAMPLE V1 '.length) as keyof typeof documentKinds
  if (markers.length !== 1 || !Object.hasOwn(documentKinds, kind)) {
    throw new Error('지원하는 추가 서류 서식이 아닙니다.')
  }

  function field(label: string, optional = false): Evidence<string> | undefined {
    const prefix = `${label} | `
    const matches = lines.filter(line => line.text.startsWith(prefix) || line.text === `${label} |`)
    const value = matches[0]?.text.slice(prefix.length).trim()
    if (optional && matches.length <= 1 && !value) return undefined
    if (matches.length !== 1 || !value) throw new Error(`${label} 항목을 확인해 주세요.`)
    return { value, page: matches[0].page, text: matches[0].text }
  }
  function required(label: string): Evidence<string> {
    return field(label)!
  }
  function amount(label: string): Evidence<number> {
    const source = required(label)
    const value = moneyValue(source.value)
    if (value === null) throw new Error(`${label} 금액을 확인해 주세요.`)
    return { ...source, value }
  }

  if (required('사례번호').value !== caseId) throw new Error('현재 진료 건과 사례번호가 다릅니다.')
  const base = { name: document.name, id: required('문서번호').value }
  switch (kind) {
    case 'DIAGNOSIS':
      return { ...base, kind, diagnosis: required('진단명'), code: field('질병분류기호', true) }
    case 'PRESCRIPTION': {
      const medications = lines.filter(line => line.text.startsWith('처방약 |')).map(line => {
        const [, name, days, extra] = line.text.split('|').map(value => value.trim())
        if (!name || !/^\d{1,3}$/.test(days ?? '') || Number(days) < 1 || extra !== undefined) {
          throw new Error('처방약 이름과 투약일수를 확인해 주세요.')
        }
        return { value: { name, days: Number(days) }, page: line.page, text: line.text }
      })
      if (medications.length === 0) throw new Error('처방약 항목을 확인해 주세요.')
      return { ...base, kind, medications }
    }
    case 'PAYMENT':
      if (required('납입 범위').value !== '해당 진료 건') throw new Error('해당 진료 건의 납입확인서가 필요합니다.')
      return { ...base, kind, paid: amount('납입액') }
    case 'PHARMACY': {
      const prescriptionId = required('처방번호')
      const covered = amount('급여 본인부담')
      const uncovered = amount('비급여')
      const paid = amount('약국 환자 부담 합계')
      if (covered.value + uncovered.value !== paid.value) throw new Error('약제비 구분별 금액과 합계가 다릅니다.')
      return { ...base, kind, prescriptionId, covered, uncovered, paid }
    }
  }
}

export function calculationInputs(
  documents: SupportingDocument[], relations: ReadonlyMap<string, PaymentRelation>,
  hospital: { total: number; reconciled: boolean; items: ReviewItem[] },
) {
  const prescriptions = documents.filter(document => document.kind === 'PRESCRIPTION')
  const payments = documents.filter(document => document.kind === 'PAYMENT')
    .map(document => ({ id: document.id, paid: document.paid, matchesHospital: document.paid.value === hospital.total }))
  const receipts = documents.filter(document => document.kind === 'PHARMACY')
  const pharmacy = receipts.map(receipt => {
    let status: 'counted' | 'included' | 'unlinked' | 'overlap' | 'unconfirmed'
    if (relations.get(receipt.id) === 'included') status = 'included'
    else if (!prescriptions.some(prescription => prescription.id === receipt.prescriptionId.value)) status = 'unlinked'
    else if (receipts.some(other => other.id !== receipt.id && other.prescriptionId.value === receipt.prescriptionId.value
      && relations.get(other.id) !== 'included')) status = 'overlap'
    else if (relations.get(receipt.id) === 'separate') status = 'counted'
    else status = 'unconfirmed'
    return { ...receipt, status }
  })
  const separatePharmacyWon = pharmacy.reduce((sum, receipt) => sum + (receipt.status === 'counted' ? receipt.paid.value : 0), 0)
  const complete = hospital.reconciled && payments.every(payment => payment.matchesHospital)
    && pharmacy.every(receipt => receipt.status === 'counted' || receipt.status === 'included')
  return {
    hospital: { patientWon: hospital.total, reconciled: hospital.reconciled,
      items: hospital.items.map(item => ({ kind: item.kind, benefit: item.benefit,
        patientWon: moneyValue(item.patient), page: item.source.page })) },
    diagnoses: documents.filter(document => document.kind === 'DIAGNOSIS'),
    prescriptions, payments, pharmacy, separatePharmacyWon,
    verifiedExpenseWon: complete ? hospital.total + separatePharmacyWon : null,
  }
}
