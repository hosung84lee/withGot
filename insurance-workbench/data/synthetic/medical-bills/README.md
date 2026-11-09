# 진료비 서류 합성 검증 세트

기존 시연 서류 한 쌍에 더해 지원 서식의 합성 PDF 세 쌍을 보관한다. 이름, 환자번호, 의료비는 테스트용으로 생성했다.

| 사례 | 영수증 | 세부내역서 | 검증 기준 |
| --- | --- | --- | --- |
| DEMO-002 급여 외래 | [영수증](covered-visit-receipt.pdf) | [세부내역서](covered-visit-details.pdf) | 환자 부담 18,000원 일치, 가상 담보 후보 두 건 |
| DEMO-003 여러 페이지 | [영수증](multipage-receipt.pdf) | [세부내역서](multipage-details.pdf) | 환자 부담 344,100원 일치, 2쪽의 영양 주사 원본 강조 |
| DEMO-004 금액 불일치 | [영수증](amount-mismatch-receipt.pdf) | [세부내역서](amount-mismatch-details.pdf) | 영수증 20,000원과 상세 합계 19,000원 불일치로 전송 차단. 테스트에서 혈액 검사 환자 부담을 14,000원으로 수정하고 재검토 |
| 사례 혼합 | DEMO-002 영수증 | DEMO-003 세부내역서 | 서로 다른 사례번호로 거절 |

앱에서 두 파일을 선택해 수동으로 검증하거나, 개발 서버와 API를 실행한 상태에서 아래 명령을 실행한다.

```text
npm --prefix apps/web run test:privacy -- medical-bills.spec.ts
```

ReportLab이 있는 Python에서 `scripts/create-synthetic-pdfs.py --validation`으로 여섯 파일을 재생성할 수 있다.
