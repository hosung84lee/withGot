import { expect, test } from '@playwright/test'

const scenarios = {
  cancer: [
    ['waiting-last', '해당 급부 지급 조건 미충족', '2024-03-31', '납입보험료 반환'],
    ['waiting-first', '가상 예상액', '10,000,000원', '기본 급부의 50% 지급'],
    ['reduction-last', '가상 예상액', '10,000,000원', '기본 급부의 50% 지급'],
    ['reduction-end', '가상 예상액', '20,000,000원', '미적용'],
    ['skin', '가상 예상액', '2,000,000원', '기타피부암 치료보험금'],
    ['in-situ', '가상 예상액', '2,000,000원', '상피내암 치료보험금'],
    ['borderline', '가상 예상액', '4,000,000원', '경계성종양 치료보험금'],
    ['repeat', '해당 급부 지급 조건 미충족', '최초 진단에 해당하지 않습니다.'],
    ['unknown-history', '계산 보류', '최초 진단 여부를 확인해 주세요.'],
    ['missing-pathology', '계산 보류', '진단확정 근거를 확인해 주세요.'],
    ['inactive', '해당 급부 지급 조건 미충족', '유효한 보험기간에 해당하지 않습니다.'],
    ['leap-anniversary', '계산 보류', '윤일 계약의 두 번째 계약해당일'],
  ],
  whole_life: [
    ['before-step', '가상 예상액', '100,000,000원', '0회'],
    ['first-step', '가상 예상액', '120,000,000원', '1회'],
    ['step-cap', '가상 예상액', '205,000,000원', '5회'],
    ['reserve-wins', '가상 예상액', '151,500,000원', '계약자적립액의 101% (최댓값)'],
    ['premiums-win', '가상 예상액', '150,000,000원', '약관상 납입보험료 (최댓값)'],
    ['death-evidence', '계산 보류', '사망 증빙을 확인해 주세요.'],
    ['death-exception', '계산 보류', '약관상 예외를 검토해 주세요.'],
    ['contract-type', '계산 보류', '계약 유형과 효력을 확인해 주세요.'],
  ],
}

for (const [category, cases] of Object.entries(scenarios)) {
  test(`simulates every ${category} fixture using the selected policy version`, async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '보험금 시뮬레이션', exact: true }).click()
    const demo = page.getByRole('region', { name: '정액보험 시뮬레이션' })
    const result = demo.getByRole('region', { name: '가상 계산 결과' })
    const amount = result.locator('.fixed-demo-amount')
    const selector = demo.getByLabel('가상 사례')
    await demo.getByLabel('보험 유형').selectOption(category)
    await expect(selector.locator('option')).toHaveCount(cases.length)

    for (const [id, status, value, detail] of cases) {
      await test.step(id, async () => {
        await selector.selectOption(id)
        await expect(result.getByText(status, { exact: true })).toBeVisible()
        if (status === '가상 예상액') await expect(amount).toHaveText(value)
        else {
          await expect(amount).toHaveCount(0)
          await expect(result).toContainText(value)
        }
        if (detail) await expect(result).toContainText(detail)
      })
    }
    await demo.getByText('공식 약관에서 근거 확인', { exact: true }).click()
    const annex = demo.getByRole('link', { name: /^별표 1 · PDF/ })
    await expect(annex).toHaveAttribute('href', category === 'cancer' ? /lina\.co\.kr.*#page=12$/ : /hanwhalife\.com.*#page=58$/)
  })
}

test('mobile changes product and result locally, then opens the policy library', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: '보험금 시뮬레이션', exact: true }).click()
  const demo = page.getByRole('region', { name: '정액보험 시뮬레이션' })
  const requests: string[] = []
  page.on('request', request => requests.push(request.url()))
  await demo.getByLabel('가상 사례').selectOption('reduction-end')
  await demo.getByLabel('보험 유형').selectOption('whole_life')
  await expect(demo.getByLabel('가상 사례')).toHaveValue('before-step')
  await expect(demo.getByText('가상 예상액', { exact: true })).toBeVisible()
  expect(await demo.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true)
  expect(requests).toEqual([])
  await demo.getByRole('button', { name: '약관 라이브러리 보기' }).click()
  await expect(page.getByRole('heading', { name: '정액보험 약관' })).toBeVisible()
})
