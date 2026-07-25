# Architecture

## 역할

- Google Drive는 라이브 Work Claim, 전체 Run Report, 원시·대형 자료와 실행 산출물을 저장한다.
- GitHub는 실행 규칙, 설정, 코드, 스키마, 재현 스크립트, 검증된 manifest와 milestone 상태를 버전 관리한다.
- ChatGPT Project는 현재 작업에 필요한 작은 문맥과 실행 채팅을 제공한다.

같은 라이브 상태를 Drive와 GitHub에 수동으로 중복 기록하지 않는다. GitHub에는 중요한 상태 변경과 재현 가능한 요약만 반영한다.

## 작업 충돌 방지

중복 비용이 크거나 재사용 가치가 높은 작업은 Work Claim으로 선점한다. 짧은 확인과 국소 분석은 기존 작업 기록 안에서 처리한다. 상태 변경 전 최신 revision과 관련 열린 PR을 다시 확인한다.

## 재사용과 검증

자료, 데이터, 차트, 특징량, 코드, 결과와 검증 증거는 stable ID와 dependency fingerprint로 재사용한다. 관련 기록만 검색하고 전체 Registry를 기본적으로 전수 검토하지 않는다.

검증은 단계적으로 적용한다. 초기 후보는 치명적 오류와 기본 비용을 빠르게 확인하고, 경제적 가능성이 확인될수록 아웃오브샘플·안정성·체결·계좌 스트레스를 확대한다.

## 다른 프로젝트에 재사용

`config/project.toml`에는 공개 가능한 프로젝트 binding을 두고, 비공개 Drive ID는 Git에서 제외되는 `config/project.local.toml`과 비공개 Drive binding에 기록한다. `scripts/init_project.py`로 프로젝트별 값을 변경한다.
