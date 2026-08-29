# Media Bridge backup과 upgrade 운영

backup은 verify 성공 전 사용하지 않고 별도 빈 DB restore drill로 복구 가능성을 확인한다. upgrade 전
현재 schema, target support, image digest, rollback image 보존을 점검한다. application rollback은 동일
schema에서만 기본 지원하며 DB downgrade는 지원 pair가 없으면 차단한다. 운영 migration과 무중단
upgrade는 아직 검증되지 않았다.

## 개인용 package update/rollback 경계

업데이트 전에는 현재 package checksum과 사용자 상태 디렉터리를 별도 백업하고, 새 package의
서명/체크섬을 확인한 뒤 적용한다. 설치 중단·health 실패 시 이전 package와 상태 snapshot을
복원한다. 소유하지 않은 OpenCodex 설정 block은 삭제하거나 덮어쓰지 않는다. 현재 커밋의
`.deb`는 QA/UNSIGNED build script와 smoke evidence만 제공하며, 자동 update/rollback과
공식 signing은 아직 미검증이다.
