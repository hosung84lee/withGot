export const outpatientPolicy = {
  title: '삼성화재 다이렉트 실손의료비보험 2605.1',
  url: 'https://direct.samsungfire.com/docs/realloss.pdf',
  benefitsPage: 26,
  limitsPage: 9,
  limitClausePage: 29,
  minimum: { clinic: 10_000, general: 20_000 },
  limits: [
    { annual: 10_000_000, visit: 100_000 },
    { annual: 30_000_000, visit: 150_000 },
    { annual: 50_000_000, visit: 200_000 },
  ],
} as const

export function estimateOutpatient({ eligible, copay, publicFund, minimum, visitLimit, remaining }: {
  eligible: number; copay: number; publicFund: number; minimum: number; visitLimit: number; remaining: number
}) {
  // Round each equivalent deduction up so the final payable amount is floored to whole won.
  const ceilRatio = (numerator: bigint, denominator: bigint) =>
    Number((numerator + denominator - 1n) / denominator)
  const percentDeduction = ceilRatio(BigInt(eligible), 5n)
  const gross = copay + publicFund
  const linkedDeduction = gross > 0
    ? ceilRatio(BigInt(eligible) * BigInt(copay), BigInt(gross)) : 0
  const deduction = Math.max(minimum, percentDeduction, linkedDeduction)
  const beforeLimits = Math.max(0, eligible - deduction)
  const payable = Math.min(beforeLimits, visitLimit, remaining)
  return { rate: gross > 0 ? copay / gross : 0, percentDeduction, linkedDeduction, deduction, beforeLimits, payable }
}
