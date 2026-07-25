# 폴더·행동 활용 계약

이 문서는 프로젝트의 지속 폴더와 반복 행동이 왜 존재하며, 언제 무엇을 넣고 무엇을 꺼내는지 정의한다. 세부 필드는 `config/folder-contract.github.toml`, `config/folder-contract.drive.toml`, `config/action-contract.toml`이 정본이다.

## 존재 판단 기준

폴더나 행동은 다음 질문에 모두 답할 수 있을 때만 유지한다.

1. 어떤 문제를 줄이는가?
2. 무엇을 입력받는가?
3. 무엇을 산출하는가?
4. 누가 다음 단계에서 사용하는가?
5. 언제 사용하고 언제 사용하지 않는가?
6. 완료와 정리 기준은 무엇인가?
7. 동일 역할의 다른 위치와 중복되지 않는가?

답하지 못하거나 실제 생산자·소비자가 없는 항목은 제거하거나 역할을 다시 정의한다.

## 저장 계층

| 위치 | 존재 이유 | 넣는 것 | 꺼내 쓰는 것 | 사용 규칙 |
|---|---|---|---|---|
| GitHub `instructions/` | 모든 실행에 적용할 안정적인 규칙 | 목표·기본조건·직접 행동 | Project Instructions | 실행 행동을 바꾸는 규칙만 둔다. 설계 배경과 과거 해설은 넣지 않는다. |
| GitHub `config/` | 도구가 읽는 공개 계약 | 프로젝트·평가·저장·작업·폴더 계약 | 검증기와 초기화 스크립트 입력 | 사용되지 않는 설정 키는 남기지 않는다. |
| GitHub `control/` | 작고 diff 가능한 지속 상태 | 상태·Champion·Work Claim·결과·검증·결정 mirror | 새 실행의 기준선 | 큰 원본이나 상세 로그는 넣지 않는다. stable ID와 증거 링크가 필요하다. |
| GitHub `data/` | Drive 자료를 찾는 작은 메타데이터 | Source·Dataset·Entity Registry, manifest, checksum | 검색·재사용·출처 추적 | 원시 대용량 파일은 Drive에 두고 여기에는 ID와 재현 정보만 둔다. |
| GitHub `research/` | 작고 지속적인 연구 지식 | 가설·실험 사양·비교 보고서·무효 지식 | 다음 실험과 Champion 비교 | 큰 결과 파일은 Drive로 보내고, 각 기록은 출처·조건·결정에 연결한다. |
| GitHub `runs/` | 실행의 정확한 체크포인트 | 작은 append-only Run Report | 상태 갱신·재개 | 한 실행당 한 보고서. 수정 대신 후속 보고서로 supersede한다. |
| GitHub `prompts/` | 반복 절차의 일관성 | 작업별 짧은 실행 절차 | 실행 순서 | 프로젝트 전역 규칙과 live state를 중복하지 않는다. |
| GitHub `schemas/` | 구조화 기록의 필수 필드 보장 | JSON Schema | writer·validator | 둘 이상의 실행이 만드는 기록만 스키마화하고 검증기에 연결한다. |
| GitHub `scripts/` | 반복 기계작업의 결정론화 | 등록·검증·초기화·context 생성 코드 | 재현 가능한 자동 처리 | 호출자·테스트·절차 중 하나가 없는 스크립트는 제거한다. |
| GitHub `templates/` | 반복 기록의 누락 방지 | Run Report·가설 템플릿 | 일관된 초안 | 스키마나 생성 절차와 연결되지 않은 템플릿은 제거한다. |
| GitHub `tests/` | 반복 실패의 자동 탐지 | 불변조건과 회귀 테스트 | CI 증거 | 보호하는 기능이나 불변조건이 사라질 때만 함께 제거한다. |
| GitHub `.github/` | 저장소 행동을 자동 강제 | CI·Issue·PR 템플릿 | 구조화된 claim·review·검증 | 실제 이벤트가 사용하지 않는 workflow/template은 유지하지 않는다. |
| GitHub `docs/` | 사람과 AI가 절차를 정확히 이해 | 구조·수명주기·운영 계약 | 필요 시 참고 | trigger·입력·산출물·완료·정리 규칙을 명시한다. |

## Google Drive 폴더

| 폴더 | 존재 이유 | 입력 → 산출물 | 완료·정리 규칙 |
|---|---|---|---|
| `00_CONTROL` | 자주 읽고 갱신하는 live control | 검증된 변경 → Project State·Champion·Work Claim·Registry·계약 | 현재 문서만 유지하고 이전 상태는 snapshot/archive로 이동 |
| `01_RUNS` | 실행별 복구 가능한 기록 | 완료 또는 시간제한 실행 → append-only Run Report | Work Claim·branch/commit/PR·입력·검증·다음 작업을 연결 |
| `02_DATA` | 재사용 가능한 자료·데이터 라이브러리 | 신규 자료·스냅샷·결정론적 변환 → stable ID가 있는 자산 | 원본은 immutable, 가공본은 versioned, 모든 지속 파일은 Registry/manifest에 연결 |
| `02_DATA/00_INBOX` | 분류 전 임시 수신 | 미분류 파일 → 정식 폴더 또는 quarantine | 해당 Work Claim 종료 전에 비워야 하며 상시 저장소로 사용하지 않음 |
| `02_DATA/10_YOUTUBE/00_RAW_TRANSCRIPTS` | 사용한 원문 자막 보존 | VTT·텍스트 → Source Registry 연결 원본 | 원본 변경 금지; 중복은 URL/hash로 재사용 |
| `02_DATA/10_YOUTUBE/10_SOURCE_NOTES` | 긴 원문을 다시 읽지 않게 함 | 등록 자막 → 출처 중심 요약·타임스탬프·구현 단서 | source ID가 없거나 단순 감상문이면 보존하지 않음 |
| `02_DATA/10_YOUTUBE/20_EXTRACTED_CLAIMS` | 외부 주장을 검증 가능한 단위로 분리 | source note → 주장·조건·타임스탬프 | 가설로 승격하거나 기각 상태를 기록; 여기에는 가설 파일을 두지 않음 |
| `02_DATA/20_PAPERS` | 논문·기술자료 재검색 방지 | 사용 자료 → 원문 또는 재현 가능한 사본·노트 | Source Registry 연결 필수 |
| `02_DATA/30_TRADERS_AND_FUNDS` | 인물·운용사 방법과 출처 재사용 | 사례 자료 → 엔터티·방법 노트 | Entity/Source ID 연결 필수 |
| `02_DATA/40_COMPETITIONS_AND_CASES` | 대회·실계좌·운영 사례 재사용 | 사례 자료 → 조건·주장·운영 단서 | 검증되지 않은 성과는 주장으로만 표시 |
| `02_DATA/50_EXCHANGES_BROKERS_APIS` | 체결·비용·데이터 계약의 공식 근거 | 공식 문서 → 버전된 수수료·주문·API 기준 | 사용한 실험·execution contract에서 source ID로 참조 |
| `02_DATA/60_CODE_AND_REPOS` | 외부 구현 반복 탐색 방지 | repository/release → commit·license·구현 노트 | 복제 코드와 단순 링크를 구분하고 commit을 고정 |
| `02_DATA/70_MARKET_AND_REFERENCE_DATA` | 실험 입력을 고정 | 시장·참조 데이터 → immutable dataset snapshot | Dataset Registry·기간·시점·hash 필수 |
| `02_DATA/80_PROCESSED_AND_EXTRACTED` | 결정론적 가공 결과 재사용 | raw source/dataset + transform → versioned processed asset | transform version·input IDs·hash 필수; 연구 결론은 두지 않음 |
| `02_DATA/90_MANIFESTS_AND_INDEXES` | 자료를 빠르게 찾고 중복을 막음 | metadata → Source·Dataset·Entity Registry·index | 현재 index 유지; 원본과 결과 자체는 두지 않음 |
| `02_DATA/99_DUPLICATES_AND_QUARANTINE` | 충돌·손상 파일이 정식 자료로 섞이는 것을 방지 | 중복·불명확·손상 파일 → 조사 대기 항목 | 일반 archive로 사용하지 않으며 해결 후 재사용·삭제·정식 등록 |
| `03_RESEARCH/10_HYPOTHESES` | 반증 가능한 연구 대상을 한곳에 유지 | reasoning/claim → 가설 ID·메커니즘·예측·최소 실험 | `02_DATA`에는 가설을 두지 않는다. 실험 또는 기각으로 연결 |
| `03_RESEARCH/20_EXPERIMENTS` | 실험 조건과 재현 명령 고정 | 가설+데이터+평가계약 → 실험 기록 | 데이터 snapshot·인과 경계·비용·검색범위·checksum 필수 |
| `03_RESEARCH/30_REPORTS` | 동일 조건의 검증된 비교 제공 | 실험 증거 → 비교·결정 보고서 | 외부 주장이나 인샘플 결과를 검증 성과로 표현하지 않음 |
| `03_RESEARCH/40_INVALIDATED_AND_REJECTED` | 실패 반복 방지 | 무효·폐기 결과 → 원인·재검토 조건 | 삭제하지 않고 재검토 조건까지 기록 |
| `04_ARTIFACTS` | Git에 부적합한 대형 실행 산출물 보관 | 실행 → 거래원장·모델·차트 묶음·로그 | result ID와 Run Report가 없는 파일은 두지 않음 |
| `05_SNAPSHOTS` | 중요한 상태 전환 복구 | material state change → 완전한 상태 snapshot | 모든 실행마다 만들지 않고 Champion/평가계약/구조의 중요 변경 시만 생성 |
| `90_ARCHIVE` | 비활성 자료가 현재 검색을 방해하지 않게 함 | 대체된 문서·legacy 구조 → 감사 가능한 archive | 현재 입력으로 사용하지 않으며 원래 위치·대체 대상·보관 이유를 기록 |

### 중복 제거

- 가설의 canonical 위치는 `03_RESEARCH/10_HYPOTHESES`다.
- `02_DATA/10_YOUTUBE/30_HYPOTHESES`는 역할이 중복되므로 사용하지 않는다.
- `04_ARTIFACTS`는 큰 실행 결과, `01_RUNS`는 실행 보고서다.
- `05_SNAPSHOTS`는 완전한 상태 복구점, `90_ARCHIVE`는 비활성 자료 보관이다.
- `80_PROCESSED_AND_EXTRACTED`는 결정론적 데이터 가공물, `03_RESEARCH`는 판단과 연구 지식이다.

## 행동 계약

| 행동 | 실행 조건 | 필수 입력 | 완료 산출물 |
|---|---|---|---|
| 현재 문맥 읽기 | 모든 작업 시작 | state·Champion·claims·registries·cache·PR | 기준 revision과 재사용 가능한 입력이 확인됨 |
| Work Claim 등록 | 본격 실행 전 | 목적·범위·지문·revision·lease·branch | 충돌 가능한 범위가 식별되는 active claim |
| Source 등록 | 새 외부 자료 사용 | canonical URL·파일/hash·메타데이터 | source ID와 Drive 위치 |
| Dataset 등록 | 새 데이터 snapshot 사용 | 공급자·시점·범위·hash·인과 정보 | immutable dataset ID |
| 주장→가설 승격 | 주장이 시험 가치 있음 | source/claim ID·메커니즘·조건 | hypothesis ID와 최소 실험 |
| 실험 실행 | 가설과 조건이 정의됨 | hypothesis·dataset·code·cost/evaluation contract | 재현 명령·증거·checksum·결정 |
| 결과 등록 | 재사용 가능한 결과 생성 | Run Report·artifacts·dependency fingerprint | Result Registry entry |
| 검증 증거 등록 | 반복 사용 가능한 검사가 완료됨 | dependency fingerprint·scope·evidence | Validation Cache entry |
| Run Report 작성 | 목표 달성 또는 시간제한 | claim·revision·작업·검증·산출물 | append-only checkpoint와 다음 작업 |
| State/Champion 갱신 | 근거가 현재 상태를 바꿈 | 결과·검증·최신 revision | revision-checked PR과 이전 Champion 보존 |
| Snapshot 생성 | 중요한 상태 전환 | current state·Champion·contract·registries | 복구 가능한 milestone snapshot |
| Archive/Quarantine | 현재 사용에서 제외해야 함 | 대상·이유·대체 위치 | 검색 경로에서 분리된 감사 가능 항목 |
| Context bundle 생성 | 새 실행이나 중요 revision | hot state와 registry index | 작고 최신인 context manifest |

## 활용 가능성을 높이는 강제 장치

- CI가 machine contract의 필수 필드, 중복 역할, GitHub 폴더 존재와 허용된 빈 폴더 정책을 검사한다.
- PR 템플릿이 Work Claim, Run Report, Result Registry, Validation Cache, 저장 위치와 정리 결정을 요구한다.
- Result Registry와 Validation Cache를 사용하지 않는 PR은 `해당 없음` 사유를 명시한다.
- 빈 폴더는 `must_not_be_empty`, `ready_on_demand`, `prefer_empty`, `prefer_absent` 중 하나로 계약된다.
- `ready_on_demand` 폴더는 첫 산출물이 생길 때만 사용하며, 장기간 빈 상태 자체는 문제가 아니다.
- `prefer_empty` 폴더는 비어 있는 것이 정상이고 항목이 남으면 해결 대상이다.
- `prefer_absent` 폴더는 생성물이며 필요할 때 만들어지고 재생성 가능하다.

## 로컬 생성 폴더

- `data/raw`, `data/downloads`: 등록 전 임시 staging이며 Work Claim 종료 전에 Drive 등록·quarantine·삭제로 정리한다.
- `data/cache`: 의존성 지문으로 재생성 가능한 cache이며 언제든 삭제할 수 있어야 한다.
- `artifacts/local`: 대형 산출물의 업로드 전 staging이며 Result Registry/Run Report에 연결한 뒤 비운다.
- `dist`: context bundle 생성물이며 재생성 가능하고 정본으로 사용하지 않는다.
