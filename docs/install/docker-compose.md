# Media Bridge Docker Compose 설치

현재 bundle은 격리 환경에서 build·onboarding·restart·backup/restore·동일 schema의 image
rollback까지 검증된 code-ready 산출물이다. 운영 배포와 다른 PC HTTPS는 아직 검증되지 않았다.

## 준비

- Docker Engine과 Compose plugin
- exact image tag/digest 검토
- `deploy/.env.example`을 기반으로 만든 non-secret `.env`
- 최초 배포 시 `deploy/scripts/secret_bootstrap.py`가 생성하는 시스템 Secret 파일
- Control/Data credential digest가 일치하도록 같은 credential pepper 원문을 각 서비스에 별도 mount

Secret 파일을 저장소에 커밋하지 않는다. Provider API 키와 client credential은 운영 화면의 DB 정본을
사용하고 `.env`에 넣지 않는다. 최초 배포 전에 다음 스크립트를 실행한다.

```bash
sudo python3 deploy/scripts/secret_bootstrap.py
```

DB 볼륨이 아직 없을 때만 DB 암호, DB URL, Control/Gateway pepper, snapshot Ed25519 key pair,
receipt secret을 생성한다. 재배포에서는 기존 파일을 검증하고 그대로 보존한다. DB 볼륨이 있는데
Secret 파일이 전부 없거나 일부만 있으면 새 키로 덮어쓰지 않고 중단한다. 이는 DB에 저장된 Provider
credential을 새 pepper로 복호화할 수 없게 되는 사고를 막는다. standalone rootful Compose의 file-backed
Secret은 DB 컨테이너 UID `999`, 애플리케이션 UID `10001`, mode `0400`으로 저장한다.

## 순서

1. `docker compose --env-file <env> -f deploy/compose.yaml config`로 rendering을 검토한다.
2. `media-bridge-db`와 `media-bridge-control`만 기동한다.
3. `deploy/scripts/bootstrap_token.py`로 일회 token을 발급하고 HTTPS Web Console에서 onboarding한다.
4. client credential, exact model capability, fail-closed policy를 만들고 signed snapshot을 발행한다.
5. 첫 snapshot 뒤 `media-bridge-data`를 기동한다. snapshot이 없거나 손상되면 ready가 되지 않는다.

DB port는 publish하지 않는다. `deploy/compose.test.yaml`은 격리 시험 전용이며 운영에 사용하지 않는다.
