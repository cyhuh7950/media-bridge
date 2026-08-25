# Media Bridge Docker Compose 설치

현재 bundle은 격리 환경에서 build·onboarding·restart·backup/restore·동일 schema의 image
rollback까지 검증된 code-ready 산출물이다. 운영 배포와 다른 PC HTTPS는 아직 검증되지 않았다.

## 준비

- Docker Engine과 Compose plugin
- exact image tag/digest 검토
- `deploy/.env.example`을 기반으로 만든 non-secret `.env`
- `deploy/secrets/README.md`에 따른 외부 Secret 파일
- Control/Data credential digest가 일치하도록 같은 credential pepper 원문을 각 서비스에 별도 mount

Secret 파일은 저장소 밖에 두고 provider key, client credential, 비밀번호, 서명 개인키를 `.env`에
넣지 않는다. standalone rootful Compose에서는 non-root UID `10001`이 읽도록 host owner와 mode
`0400`을 맞춘다.

## 순서

1. `docker compose --env-file <env> -f deploy/compose.yaml config`로 rendering을 검토한다.
2. `media-bridge-db`와 `media-bridge-control`만 기동한다.
3. `deploy/scripts/bootstrap_token.py`로 일회 token을 발급하고 HTTPS Web Console에서 onboarding한다.
4. client credential, exact model capability, fail-closed policy를 만들고 signed snapshot을 발행한다.
5. 첫 snapshot 뒤 `media-bridge-data`를 기동한다. snapshot이 없거나 손상되면 ready가 되지 않는다.

DB port는 publish하지 않는다. `deploy/compose.test.yaml`은 격리 시험 전용이며 운영에 사용하지 않는다.
