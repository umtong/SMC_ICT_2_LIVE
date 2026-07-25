# Durable data library

이 라이브러리는 같은 자료의 재검색·재다운로드·재요약, 차트 재구성, 중복 가설 추출을 줄인다.

## 등록 절차

1. 외부 검색 전에 Source·Dataset·Entity·Result Registry, Validation Cache와 활성 Work Claim을 확인한다.
2. URL을 정규화하고 저장 파일의 SHA-256을 계산한다.
3. 동일 URL이나 hash가 있으면 기존 자료를 재사용한다. 충돌하는 중복은 quarantine에 둔다.
4. 공개된 정보와 자료를 자유롭게 사용한다.
5. 작업에 사용하거나 재사용 가치가 높은 자료를 Drive의 canonical folder에 보존하고 원본은 변경하지 않는다.
6. 메타데이터와 Drive 경로를 registry에 한 번 기록한다.
7. 원본과 분리하여 출처 노트와 추출 주장을 만든다.
8. 반증 가능한 가설은 `03_RESEARCH/10_HYPOTHESES`에 기록한다.
9. 후속 실험과 결과에 source ID, dataset ID, code commit, evaluation contract와 dependency fingerprint를 기록한다.
10. 의존성이 바뀌지 않은 가공 산출물과 검증 증거를 재사용한다.

## canonical 구분

- `80_PROCESSED_AND_EXTRACTED`: 원시 자료·데이터에서 결정론적으로 만든 정규화 텍스트, 특징량, 변환 데이터
- `03_RESEARCH`: 가설, 실험 조건, 비교 판단과 무효 지식
- `04_ARTIFACTS`: 거래 원장·모델·대형 차트 묶음처럼 Git에 부적합한 실행 산출물

대형 파일은 Drive에 두고 Git에는 manifest, checksum, transform version과 재현 정보만 보관한다. 상세 폴더 수명주기는 `config/folder-contract.drive.toml`과 `docs/folder-action-contract.md`를 따른다.
