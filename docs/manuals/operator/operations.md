# Media Bridge 운영자 매뉴얼

운영자는 DB→Control→onboarding/snapshot→Data 순서를 지킨다. Control 중단 중 Data는 마지막 정상 signed
snapshot으로 계속 ready일 수 있지만 새 policy나 revoke는 반영되지 않으므로 outage를 장기 정상 상태로
간주하지 않는다. health, audit, volume 여유, snapshot version을 관찰하고 실제 provider body나 media를
운영 로그에 저장하지 않는다.
