# Linux에서 Media Bridge 설치·실행

## 일반 사용자 설치

일반 사용자는 npm 패키지만 설치합니다.

```bash
npm install -g @cyhuh/media-bridge
mb init
mb start
```

시스템 전역 경로(`/usr/local`)에 쓸 권한이 없는 계정은 사용자 전역 prefix를 먼저 지정합니다.
이 경우 npm이 만드는 실행 링크가 `~/.local/bin`에 놓이므로 PATH에도 등록해야 합니다.

```bash
npm config set prefix "$HOME/.local"
npm install -g @cyhuh/media-bridge
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$PATH"
command -v mb
```

`command -v mb`가 경로를 출력하면 설치가 완료된 것입니다. `sudo npm install -g`로 우회하지
않고 사용자 prefix를 사용합니다.

사용자는 Python, Docker, PostgreSQL 또는 `.deb` 명령을 직접 실행하지 않습니다.
Eoul Gateway와 함께 자동 설치할 때는 이 패키지를 먼저 설치한 뒤, Gateway의 실행 방식에 맞는
bind 주소를 `mb init --host`로 전달합니다. `npm install` 자체는 주소를 추측하지 않습니다.

## `mb init` 설정

`mb init`에서 Media Bridge bind 주소(기본 `127.0.0.1`), OpenCodex 주소, Media Bridge 포트(기본 `8642`), Solar 모델·HTTPS
endpoint·Secret 참조, OCR/Vision 변환 기본값, 변환 실패 시 Solar 전송 차단 정책을 입력합니다.
설정은 `$HOME/.media-bridge/config.json`에 저장되며 Secret 원문은 저장하지 않습니다.

Docker 컨테이너처럼 다른 네트워크 네임스페이스의 소비자가 같은 PC의 Media Bridge를 호출해야
하면 사설 IPv4 bind 주소를 지정합니다. Docker 기본 bridge gateway가 `172.17.0.1`인 경우:

```bash
mb init --host 172.17.0.1 --port 8642
```

비대화식 설치에서는 `MB_HOST=172.17.0.1 MB_PORT=8642 mb init`을 사용할 수 있습니다.
HTTP bind 주소는 loopback 또는 `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` 사설 IPv4만
허용하며 공인 주소는 거부합니다. 주소를 생략하면 기본값 `127.0.0.1`을 유지합니다.
설정은 사용자 홈에 저장되므로 패키지를 다시 설치해도 자동으로 `172.17.0.1`로 바뀌지 않습니다.

## 명령

```bash
mb init
mb start [--port 8642]
mb stop
mb status
mb health [--json]
mb gui
mb service install
mb service start
mb service stop
mb service restart
mb service uninstall
mb update
```

`mb gui`는 데스크톱에서는 로컬 설정 화면을 열고 headless 서버에서는 현재 설정된 Web 주소를
표시합니다. 설정 저장 후 `mb service restart`로 적용합니다. `mb health`가 실패하면 Media Bridge가
준비되지 않은 상태입니다. runtime artifact가 없는 경우에는 Python이나 `.deb`를 직접
설치하지 말고 지원 플랫폼 release 준비 여부를 확인합니다.

## 내부 배포·복구용 `.deb`

`.deb`는 일반 사용자 설치 경로가 아니라 내부 배포·복구용 artifact로 유지합니다.
checksum, `dpkg`, service와 운영 설치 검증은 운영자 절차 및 별도 승인 범위입니다.

## 현재 미검증 범위

- npm registry 공개와 실제 원격 `npm install -g`
- Linux 아키텍처별 runtime artifact release
- 실제 OpenCodex 연결과 Solar Provider 호출
- systemd 자동 시작과 다른 PC 브라우저
