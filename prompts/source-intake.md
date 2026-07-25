# Source intake prompt

기존 Source·Entity Registry를 먼저 확인한다. 새로운 자료는 URL을 정규화하고, 필요한 메타데이터를 기록하며, 저장 파일의 hash를 계산하고, 작업에 사용한 자료를 지정된 Drive 폴더에 보존한 뒤 registry에 한 번 등록한다.

동일 canonical URL이나 SHA-256이 있으면 기존 자료를 재사용한다. 자료에서 핵심 주장, 구현 단서와 반증 가능한 가설을 source ID와 함께 추출한다. 외부 작성자의 전체 성공 여부보다 추출한 아이디어를 우리 환경에서 직접 검증하는 데 집중한다.
