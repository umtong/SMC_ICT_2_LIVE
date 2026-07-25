# Data retention, provenance, and reuse

- 공개된 정보와 자료를 자유롭게 사용한다.
- 전략·가설·구현·검증에 사용하거나 재사용 가치가 높은 자료를 등록한다.
- 저장한 원본은 변경하지 않고, 가공본은 버전 관리하며 source ID·transform version·timestamp·checksum을 기록한다.
- 전체 영상은 영상 자체가 고유한 연구 가치를 제공할 때만 저장한다. 일반적으로 canonical URL, 메타데이터, 자막, 출처 노트, 추출 주장과 가설을 보존한다.
- 논문, 기술 문서, 트레이더·운용사 자료, 대회 사례, 코드 저장소, API 문서와 시장 자료에 같은 등록·재사용 절차를 적용한다.
- canonical URL과 SHA-256으로 중복을 확인한다. 동일 자료는 재사용하고 충돌하는 중복은 원본을 덮어쓰지 않고 quarantine에 둔다.
- 지속 보관 파일은 registry 또는 manifest에서 검색 가능해야 한다.
- 가설은 `03_RESEARCH/10_HYPOTHESES`, 대형 실행 산출물은 `04_ARTIFACTS`, 중요 상태 복구점은 `05_SNAPSHOTS`에만 둔다.
- 임시 inbox·download staging·local artifacts는 해당 Work Claim 종료 전에 정식 등록·quarantine·삭제로 정리한다.
- 오래된 snapshot과 대체된 가공 산출물은 archive로 이동하고 현재 registry는 작고 검색 가능하게 유지한다.
- 세부 수명주기는 `config/folder-contract.drive.toml`과 `docs/folder-action-contract.md`를 따른다.
