# Media Bridge credential, snapshot, audit

bootstrap token, recovery code, client credential은 한 번만 표시한다. DB에는 password hash와 credential
digest만 남는다. Provider는 환경변수/Docker Secret/외부 Secret Store reference만 저장한다. snapshot
private key는 Secret으로 주입하고 DB에는 key ID와 공개 정보만 둔다. snapshot 발행·rollback 전 validated
draft와 target version을 확인하며 audit에는 본문과 Secret이 아닌 행위·대상·safe status만 남긴다.
