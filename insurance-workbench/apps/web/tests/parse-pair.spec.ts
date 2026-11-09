import { expect, test } from '@playwright/test'
import { parsePair } from '../src/privacy'
import type { LocalDocument } from '../src/privacy'

function document(name: string, rows: string[]): LocalDocument {
  return { name, pages: [{ url: '', width: 595, height: 842, lines: rows.map((text, index) => ({
    text, page: 1, left: 42, top: index * 35, width: 200, height: 12,
  })) }] }
}

const receipt = document('receipt.pdf', [
  'BOJANGIT SAMPLE V1 RECEIPT', '사례번호 | DEMO-001', '환자 부담 합계 | 480000',
])
const details = (caseNumber = 'DEMO-001', count = 1, markers = ['BOJANGIT SAMPLE V1 DETAIL']) =>
  document('details.pdf', [...markers, `사례번호 | ${caseNumber}`, `항목 수 | ${count}`,
    '치료 | 복부 MRI | 비급여 | 480000 | 480000'])

test('pairs reversed document order and preserves the detail source location', () => {
  const result = parsePair([details(), receipt])
  expect(result.patientTotal).toBe(480000)
  expect(result.items).toMatchObject([{ kind: 'mri', document: 0, source: { page: 1 } }])
})

test('stops when case identifiers or row counts differ', () => {
  expect(() => parsePair([receipt, details('DEMO-002')])).toThrow('서로 다른 사례')
  expect(() => parsePair([receipt, details('DEMO-001', 2)])).toThrow('치료 항목 수')
})

test('rejects a PDF declaring conflicting document roles', () => {
  const mixed = details('DEMO-001', 1, ['BOJANGIT SAMPLE V1 DETAIL', 'BOJANGIT SAMPLE V1 RECEIPT'])
  expect(() => parsePair([receipt, mixed])).toThrow('한 쌍')
})
