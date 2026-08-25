# Media Bridge 연결과 시험

Web Console에서 client credential 발급은 연결 성공이 아니다. Connection에는 Gateway URL과 외부
credential Secret 참조를 저장한다. Preview는 downstream 호출 0회이고, 실제 downstream 시험은
비용 안내를 매번 명시적으로 opt-in해야 한다. browser는 same-origin `/admin/v1`만 호출하며 media와
credential을 storage에 보존하지 않는다. 실제 provider 연결은 아직 검증되지 않았다.
