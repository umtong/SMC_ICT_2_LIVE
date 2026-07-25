# Causal Alpha Wave 1

`CLM-GPT56-20260725-001`의 실행 범위다. 등록된 한국어 YouTube 자막에서 추출한 SMC/ICT 가설을 공식 Binance USD-M 자료와 동일한 비용·체결 계약으로 비교한다.

## 시간 분할

- Warm-up: 2021-10-01 to 2021-12-31 UTC
- Development: 2022-01-01 to 2022-12-31 UTC
- Frozen validation: 2023-01-01 to 2023-12-31 UTC
- 2023 자료는 개발 게이트를 통과한 후보와 freeze manifest가 생성된 경우에만 다운로드·평가한다.

## 정보 가용성

- 5분 특징은 해당 봉이 완전히 종료된 뒤에만 알려진다.
- 신호의 최초 체결은 다음 실제 1분봉 시가다.
- rolling high/low, ATR, 표준화 기준과 상위 시간축 상태는 현재 신호봉 전에 완료된 자료만 사용하거나, 현재 완료봉을 사용하는 항목은 명시한다.
- 결측 1분봉을 채우지 않는다. 특징창·진입·보유경로가 결측을 통과하면 신호 또는 거래를 폐기한다.
- 동일 분 손절과 다른 종료 조건이 충돌하면 손절을 우선한다.
- BTC·ETH 전체에서 pending/open 최대 한 슬롯이다.

## 비용 계약

- base: 왕복 16bp
- stress: 왕복 24bp
- hard: 왕복 32bp
- 보호손절: 추가 4bp
- 실제 Binance 역사적 funding을 `(entry, exit]` 구간에 적용한다.
- 1차 알파 스크린은 1배 고정 명목노출이다. 위험률·레버리지 최적화는 수행하지 않는다.

## 개발 게이트

- 80 trades 이상
- base와 stress 모두 순로그성장 양수
- base PF >= 1.10
- base 중앙 거래수익 > 0
- 양수 분기 >= 3/4
- 상위 10개 승리 비중 <= 35%
- 상위 10개 승리 제거 후 순로그성장 > 0
- 최대낙폭 <= 15%

통과 후보만 family별 최대 2개, 거래집합 Jaccard 중복 85% 이하로 동결한다.

## 검증 게이트

- 60 trades 이상
- base와 stress 모두 순로그성장 양수
- base PF >= 1.05
- base 중앙 거래수익 > 0
- 양수 분기 >= 3/4
- 상위 10개 승리 비중 <= 40%
- 상위 10개 승리 제거 후 순로그성장 > 0
- 최대낙폭 <= 20%

이 스크린은 PRE-LIVE 완료 판정이 아니다. 통과 후보는 1분 봉내 실행 감사, 비용·지연·용량 스트레스, 반복 워크포워드와 별도 봉인 OOS로 이동한다.

## 로컬 재현

```bash
python research/alpha_wave1/reconstruct_source.py
python -m pip install -r research/alpha_wave1/requirements-lock.txt
pytest -q tests/test_alpha_wave1.py
```

`SOURCE_MANIFEST.json`은 분할 보관된 가독 가능한 Python source fragment와 재구성된 전체 파일의 SHA-256을 고정한다.
