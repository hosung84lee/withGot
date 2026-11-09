import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { calculationInputs, parseSupportingDocument } from '../src/supplemental'

test('shows the six supported sample links upfront and accepts an individually downloaded PDF', async ({ page }) => {
  await page.goto('/')
  const catalog = page.getByLabel('첨부 가능한 추가 서류')
  await expect(catalog.getByRole('link')).toHaveCount(4)
  await expect(page.getByRole('link', { name: '진료비 영수증 샘플 PDF', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: '진료비 세부내역서 샘플 PDF', exact: true })).toBeVisible()
  for (const link of await catalog.getByRole('link').all()) {
    const url = await link.getAttribute('href')
    const response = await page.request.get(url!)
    expect(response.ok()).toBe(true)
    expect((await response.body()).subarray(0, 5).toString()).toBe('%PDF-')
  }
  const [download] = await Promise.all([
    page.waitForEvent('download'), catalog.getByRole('link', { name: '진단서 샘플 PDF' }).click(),
  ])
  const buffer = await readFile(await download.path())
  await page.getByRole('button', { name: '가상 샘플로 시작', exact: true }).click()
  const panel = page.getByLabel('추가 서류와 계산 기초자료')
  await panel.getByLabel('추가 PDF 선택').setInputFiles({
    name: download.suggestedFilename(), mimeType: 'application/pdf', buffer,
  })
  await expect(panel.getByLabel('구조화한 추가 서류')).toContainText('DEMO-DX-01')
  await expect(panel.getByLabel('첨부 가능한 추가 서류')).toContainText('첨부 1건')
})

test('reads all supporting PDFs and adds only separately paid pharmacy expenses locally', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '가상 샘플로 시작', exact: true }).click()
  await page.getByRole('button', { name: '가상 추가 서류 4종 불러오기' }).click()
  const panel = page.getByLabel('추가 서류와 계산 기초자료')
  await expect(panel.getByRole('heading', { name: '약제비 영수증', exact: true })).toBeVisible()
  await expect(panel).toContainText('DEMO-DX-01')
  await expect(panel).toContainText('가상 처방약 B | 5')
  await expect(panel).toContainText('영수증 환자 부담액과 일치')
  await expect(panel).toContainText('비용 대조 확인 필요')
  const relation = panel.getByLabel('PH-001 약제비 납부 관계')
  const totals = panel.getByLabel('비용 대조 결과')
  await relation.selectOption('separate')
  await expect(totals).toContainText('575,550원')
  const inputs = JSON.parse((await panel.getByTestId('calculation-inputs').textContent())!)
  expect(inputs).toMatchObject({ verifiedExpenseWon: 575550, separatePharmacyWon: 12400,
    pharmacy: [{ covered: { value: 10000, page: 1 }, uncovered: { value: 2400 }, status: 'counted' }] })
  await relation.selectOption('included')
  await expect(totals).toContainText('계산용 환자 부담액 합계 563,150원')
  await relation.selectOption('separate')
  await page.getByLabel('항목과 합계 검토 완료').check()
  await page.getByRole('button', { name: '전송 내용 확인', exact: true }).click()
  const requested = page.waitForRequest('**/api/coverage/candidates')
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회' }).click()
  const request = await requested
  for (const excluded of ['RX-001', 'DEMO-DX-01', '12400', 'pharmacy', 'payment']) {
    expect(request.postData()).not.toContain(excluded)
  }
  await expect(page.getByLabel('보장 후보 조회 결과')).toBeVisible()
  await panel.getByRole('button', { name: 'prescription.pdf 빼기' }).click()
  await expect(panel).toContainText('같은 처방번호의 처방전 필요')
  await expect(totals).toContainText('비용 대조 확인 필요')
  await page.getByRole('button', { name: '세션 초기화' }).click()
  await expect(panel).toHaveCount(0)
})

test('rejects a duplicate and rejects supplemental files from another visit', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '가상 샘플로 시작', exact: true }).click()
  await page.getByRole('button', { name: '가상 추가 서류 4종 불러오기' }).click()
  const panel = page.getByLabel('추가 서류와 계산 기초자료')
  await expect(panel.getByRole('heading', { name: '약제비 영수증', exact: true })).toBeVisible()
  const diagnosis = resolve('public/samples/supplements/diagnosis.pdf')
  await panel.getByLabel('추가 PDF 선택').setInputFiles(diagnosis)
  await expect(panel.getByRole('alert')).toContainText('이미 있습니다')
  await expect(panel.getByRole('heading', { name: '진단서', exact: true })).toHaveCount(1)
  const pair = resolve('../../data/synthetic/medical-bills')
  await page.getByLabel('영수증과 세부내역서 선택').setInputFiles([
    resolve(pair, 'covered-visit-receipt.pdf'), resolve(pair, 'covered-visit-details.pdf'),
  ])
  await expect(page.getByText('영수증 환자 부담 18,000원')).toBeVisible()
  await panel.getByLabel('추가 PDF 선택').setInputFiles(diagnosis)
  await expect(panel.getByRole('alert')).toContainText('사례번호가 다릅니다')
  await expect(panel.getByLabel('구조화한 추가 서류')).toHaveCount(0)
})

function supportingPdf(kind: string, id: string, fields: string[]) {
  const lines = [`BOJANGIT SAMPLE V1 ${kind}`, '사례번호 | TEST-1', `문서번호 | ${id}`, ...fields]
  return parseSupportingDocument({ name: `${id}.pdf`, pages: [{ url: '', width: 1, height: 1,
    lines: lines.map(text => ({ text, page: 1, top: 0, left: 0, height: 1, width: 1 })) }] }, 'TEST-1')
}

test('withholds the calculation total for overlapping receipts or an inconsistent payment', () => {
  const prescription = supportingPdf('PRESCRIPTION', 'RX', ['처방약 | 시연 약 | 3'])
  const fees = ['처방번호 | RX', '급여 본인부담 | 1000', '비급여 | 0', '약국 환자 부담 합계 | 1000']
  const first = supportingPdf('PHARMACY', 'A', fees)
  const second = supportingPdf('PHARMACY', 'B', fees)
  const payment = supportingPdf('PAYMENT', 'PAY', ['납입 범위 | 해당 진료 건', '납입액 | 2999'])
  const hospital = { total: 3000, reconciled: true, items: [] }
  const relations = new Map([['A', 'separate']] as const)
  const overlap = calculationInputs([prescription, first, second], relations, hospital)
  expect(overlap.pharmacy.map(item => item.status)).toEqual(['overlap', 'overlap'])
  expect(overlap.verifiedExpenseWon).toBeNull()
  const inconsistent = calculationInputs([prescription, first, payment], relations, hospital)
  expect(inconsistent.payments[0].matchesHospital).toBe(false)
  expect(inconsistent.verifiedExpenseWon).toBeNull()
})
