# Durable data library

자료 라이브러리는 같은 자료의 재검색·재다운로드·재해석과 동일 차트·가설의 반복 생성을 줄인다.

## Source classes

- YouTube videos and transcripts
- papers and technical reports
- day traders, funds, public performance cases, and competitions
- exchange, broker, API, fee, and market-data documentation
- code repositories and implementations
- market and reference datasets

## Intake contract

1. 수행 중인 범위와 관련된 Source·Dataset·Entity·Result·Work Claim 항목만 검색한다.
2. 동일 canonical URL이나 SHA-256이 있으면 기존 자료를 재사용한다.
3. 실제 가설·구현·검증에 사용했거나 다른 작업에서 다시 찾을 가능성이 높은 자료만 등록한다.
4. 초기 등록은 Source ID, URL 또는 파일, 자료 유형, 핵심 관련성, 사용한 가설·실험과 원본 위치처럼 검색·재현에 필요한 최소 항목으로 시작한다.
5. 저장한 원본은 변경하지 않고 가공본은 버전 관리한다. 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다.
6. 자료의 주장과 프로젝트의 검증 결과를 분리하고, downstream 실험에는 Source ID와 dependency fingerprint를 연결한다.
7. 사용하지 않은 검색 결과와 일회성 배경 자료를 등록하지 않는다.

Git은 `data/raw`, `data/cache`, `data/downloads`의 대형 원본을 추적하지 않는다. 대형 파일은 Drive에 두고 Git에는 manifest, checksum, 변환 코드와 재현 요약을 저장한다.
