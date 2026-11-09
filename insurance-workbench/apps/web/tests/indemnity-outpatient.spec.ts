import { expect, test, type Locator } from '@playwright/test'
import { estimateOutpatient } from '../src/indemnity-outpatient'

async function confirmConditions(estimate: Locator, facility = 'clinic', remaining = '50000000') {
  await estimate.getByLabel('질병 통원 보장 범위').selectOption('included')
  await estimate.getByLabel('의료기관 유형').selectOption(facility)
  await estimate.getByLabel('질병급여 가입금액').selectOption('50000000')
  await estimate.getByLabel('연간 잔여 한도 (원)').fill(remaining)
}

test('reproduces the published copay example and applies limits and whole-won rounding', () => {
  const example = { eligible: 200000, copay: 200000, publicFund: 300000,
    minimum: 10000, visitLimit: 200000, remaining: 50000000 }
  expect(estimateOutpatient(example)).toMatchObject({ rate: 0.4, deduction: 80000, payable: 120000 })
  expect(estimateOutpatient({ ...example, visitLimit: 100000 })).toMatchObject({ payable: 100000 })
  expect(estimateOutpatient({ ...example, remaining: 80000 })).toMatchObject({ payable: 80000 })
  expect(estimateOutpatient({ ...example, eligible: 30001, copay: 30001, publicFund: 30000 }))
    .toMatchObject({ linkedDeduction: 15001, payable: 15000 })
})

test('estimates one visit, distinguishes zero and exclusions, and keeps the computation local', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '가상 샘플로 시작', exact: true }).click()
  const estimate = page.getByRole('region', { name: '실손 급여 통원 계산' })
  const result = estimate.getByRole('status')
  let posts = 0
  page.on('request', request => { if (request.method() === 'POST') posts++ })
  await expect(result).toContainText('계산 보류')
  await confirmConditions(estimate)
  await expect(result).toContainText('원본 대조 완료')
  await page.getByLabel('항목 1 조회 선택').uncheck()
  await page.getByLabel('항목과 합계 검토 완료').check()
  await expect(result.locator('.outpatient-amount')).toHaveText('8,150원')
  await expect(result).toContainText('18,150원 · 병원 18,150원')
  await estimate.getByLabel('연간 잔여 한도 (원)').fill('2000')
  await expect(result.locator('.outpatient-amount')).toHaveText('2,000원')
  await estimate.getByLabel('연간 잔여 한도 (원)').fill('0')
  await expect(result).toContainText('잔여 한도 적용 후 지급액 0원')
  await estimate.getByLabel('연간 잔여 한도 (원)').fill('50000000')
  await estimate.getByLabel('의료기관 유형').selectOption('general')
  await expect(result).toContainText('공제 후 지급액 0원')
  await estimate.getByLabel('질병 통원 보장 범위').selectOption('excluded')
  await expect(result).toContainText('보장 제외')
  await expect(result.locator('.outpatient-amount')).toHaveCount(0)
  await estimate.getByText('입력 서류와 적용 약관', { exact: true }).click()
  await estimate.getByRole('button', { name: /계산 근거 원본/ }).first().click()
  await expect(page.getByLabel('선택한 치료의 원본 위치')).toBeVisible()
  expect(posts).toBe(0)
})

test('combines separately paid eligible pharmacy costs once and pauses for missing fund data', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '가상 샘플로 시작', exact: true }).click()
  await page.getByRole('button', { name: '가상 추가 서류 4종 불러오기' }).click()
  const relation = page.getByLabel('PH-001 약제비 납부 관계')
  const estimate = page.getByRole('region', { name: '실손 급여 통원 계산' })
  const result = estimate.getByRole('status')
  await expect(relation).toBeVisible()
  await expect(result).toContainText('납입액과 약제비 관계를 대조')
  await relation.selectOption('separate')
  await confirmConditions(estimate)
  await page.getByLabel('항목과 합계 검토 완료').check()
  await expect(result).toContainText('급여 공단부담금을 약제비 영수증에서 확인')
  await estimate.getByLabel(/약제비 급여 공단부담금/).fill('20000')
  await expect(result.locator('.outpatient-amount')).toHaveText('18,150원')
  await expect(result).toContainText('28,150원 · 병원 18,150원 + 약국 10,000원')
  await relation.selectOption('included')
  await confirmConditions(estimate)
  await expect(result.locator('.outpatient-amount')).toHaveText('8,150원')
  await expect(estimate.getByLabel(/약제비 급여 공단부담금/)).toHaveCount(0)
})
