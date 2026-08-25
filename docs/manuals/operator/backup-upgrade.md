# Media Bridge backup과 upgrade 운영

backup은 verify 성공 전 사용하지 않고 별도 빈 DB restore drill로 복구 가능성을 확인한다. upgrade 전
현재 schema, target support, image digest, rollback image 보존을 점검한다. application rollback은 동일
schema에서만 기본 지원하며 DB downgrade는 지원 pair가 없으면 차단한다. 운영 migration과 무중단
upgrade는 아직 검증되지 않았다.
