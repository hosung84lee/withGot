import { expect, test, type Page } from '@playwright/test'
import { resolve } from 'node:path'

const fixture = (name: string) => resolve('../../data/synthetic/medical-bills', `${name}.pdf`)

function selectPair(page: Page, receipt: string, details = receipt) {
  return page.getByLabel('영수증과 세부내역서 선택').setInputFiles([
    fixture(`${receipt}-receipt`), fixture(`${details}-details`),
  ])
}

test('covered-only pair matches the receipt and produces two candidates', async ({ page }) => {
  await page.goto('/')
  await selectPair(page, 'covered-visit')
  await expect(page.getByText('영수증 환자 부담 18,000원')).toBeVisible()
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  await expect(page.getByLabel('항목 2 환자 부담')).toHaveValue('12000')
  await page.getByLabel('항목과 합계 검토 완료').check()
  await page.getByRole('button', { name: '전송 내용 확인', exact: true }).click()
  await page.getByRole('button', { name: '확인한 항목으로 서버 조회' }).click()
  const candidates = page.locator('.privacy-result-list').getByRole('button')
  await expect(candidates).toHaveCount(2)
  for (const candidate of await candidates.all()) await expect(candidate).toContainText('보장 후보')
})

test('multipage pair reconciles and preserves the second-page source', async ({ page }) => {
  await page.goto('/')
  await selectPair(page, 'multipage')
  await expect(page.getByText('영수증 환자 부담 344,100원')).toBeVisible()
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  await expect(page.getByLabel('항목 4 환자 부담')).toHaveValue('30000')
  await page.getByRole('button', { name: '원본 위치 · 2쪽', exact: true }).last().click()
  await expect(page.locator('.privacy-original')).toContainText('영양 주사 | 비급여 | 30000 | 30000')
  await expect(page.getByLabel('선택한 치료의 원본 위치')).toBeVisible()
})

test('a mismatched total blocks transmission until the amount is reviewed and corrected', async ({ page }) => {
  let posts = 0
  page.on('request', request => { if (request.method() === 'POST') posts++ })
  await page.goto('/')
  await selectPair(page, 'amount-mismatch')
  await expect(page.getByText('영수증 환자 부담 20,000원')).toBeVisible()
  await expect(page.getByText('전체 항목 환자 부담 19,000원')).toBeVisible()
  await page.getByLabel('항목과 합계 검토 완료').check()
  const review = page.getByRole('button', { name: '전송 내용 확인', exact: true })
  await expect(review).toBeDisabled()
  await page.getByLabel('항목 2 환자 부담').fill('14000')
  await expect(page.getByText('합계 일치', { exact: true })).toBeVisible()
  await expect(review).toBeDisabled()
  await page.getByLabel('항목과 합계 검토 완료').check()
  await expect(review).toBeEnabled()
  expect(posts).toBe(0)
})

test('two well-formed PDFs from different cases are rejected', async ({ page }) => {
  await page.goto('/')
  await selectPair(page, 'covered-visit', 'multipage')
  await expect(page.getByRole('alert')).toContainText('서로 다른 사례의 서류')
  await expect(page.getByLabel('치료 항목 검토')).toHaveCount(0)
})
