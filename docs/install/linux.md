# Linux에서 Media Bridge 설치·중지·제거

이 문서는 Ubuntu 또는 Debian Linux에서 Media Bridge를 설치하고, 처음 설정하고, 사용하고,
중지하고, 업데이트하고, 이전 버전으로 되돌리고, 제거하는 순서입니다.

개인용 설치에는 Docker, PostgreSQL, Redis, Python, Node를 따로 설치하지 않습니다.
Debian package에 필요한 실행 환경이 포함됩니다.

## 1. GitHub에서 설치 파일 받기

가장 쉬운 설치 방법은 소스 코드를 내려받아 직접 빌드하는 것이 아니라 GitHub Release의
완성된 Debian 설치 파일을 받는 것입니다. 이 방식은 Python, Node, Docker, PostgreSQL,
Redis를 따로 설치하지 않습니다. 현재 Release workflow가 만드는 파일은 `amd64` Linux용입니다.

GitHub 저장소의 Releases에서 버전을 확인한 뒤 다음 명령을 그대로 실행합니다.

```bash
VERSION=0.1.0
ARCH=amd64
BASE="https://github.com/cyhuh7950/media-bridge/releases/download/v${VERSION}"
curl -fL -o "media-bridge_${VERSION}_${ARCH}.deb" "${BASE}/media-bridge_${VERSION}_${ARCH}.deb"
curl -fL -o "media-bridge_${VERSION}_${ARCH}.deb.sha256" "${BASE}/media-bridge_${VERSION}_${ARCH}.deb.sha256"
sha256sum -c "media-bridge_${VERSION}_${ARCH}.deb.sha256"
```

`sha256sum ...: OK`가 나오면 다음 설치 절차로 이동합니다. 해당 버전의 Release 파일이
아직 없으면 저장소의 소스 설치 절차가 아니라, 담당자가 만든 검증된 `.deb` 파일을 준비해야
합니다. GitHub Release 파일은 태그가 생성되고 workflow가 성공한 뒤에만 생깁니다.

## 2. 설치 파일 확인

Debian 파일이 있는 폴더에서 실행합니다.

```bash
cd /설치파일이-있는-폴더
VERSION=0.1.0
ARCH=amd64
DEB="media-bridge_${VERSION}_${ARCH}.deb"
ls -l "$DEB"
sha256sum "$DEB"
dpkg-deb --info "$DEB"
```

예를 들어 Release 버전이 `0.1.0`이고 컴퓨터가 `amd64`이면 실제 파일명은
`media-bridge_0.1.0_amd64.deb`입니다. `VERSION`은 받은 파일명과 같은 버전으로 바꿉니다.
공식 서명이 없는 QA 파일은 개발·테스트에서만 사용합니다.

## 3. 설치·시작

```bash
sudo dpkg -i "./media-bridge_${VERSION}_${ARCH}.deb"
systemctl --user daemon-reload
systemctl --user enable --now media-bridge-web.service
systemctl --user enable --now media-bridge-data.service
systemctl --user --no-pager status media-bridge-web.service media-bridge-data.service
```

두 service에 `active (running)`이 표시되어야 합니다.

## 4. 최초 설정

브라우저에서 `http://127.0.0.1:8765/`를 엽니다. 화면에 다음 값을 입력합니다.

1. OpenCodex endpoint
2. Solar endpoint
3. 실제 Solar model ID
4. Solar credential 환경변수 이름 또는 OS credential reference 이름
5. 필요한 경우 OCR endpoint와 Vision endpoint·model ID
6. Solar RPM: 기본값 `2000`
7. Solar TPM: 기본값 `750000`

API key 원문은 입력하지 않습니다. 설정 저장 후 페이지를 새로고침해 값이 유지되는지 확인합니다.
Data 상태는 `http://127.0.0.1:8766/status`에서 확인합니다.

## 5. OpenCodex 연결과 화면 요청

OpenCodex endpoint에는 `http://127.0.0.1:8766/v1`을 지정합니다. 기존 설정을 덮어쓰지 말고
별도 profile에서 먼저 확인합니다.

1. OpenCodex에서 코딩 작업을 시작합니다.
2. 코드, 오류 밑줄, 파일·라인, 터미널 결과가 보이는 화면을 캡처합니다.
3. 캡처와 수정 요청을 함께 보냅니다.
4. Media Bridge가 화면을 판독하고, 충분한 경우 이미지 원문을 제거한 설명 텍스트만 전달합니다.
5. Solar의 코딩 응답을 확인합니다.

판독이 충분하지 않으면 Solar로 보내지 않고 재캡처 안내를 표시합니다. 화면 확대, 오류 영역
자르기, 고해상도 유지, 여러 장 분리, 오류 문구 직접 입력을 사용합니다.

## 6. 상태 확인·재시작·중지

```bash
systemctl --user --no-pager status media-bridge-web.service media-bridge-data.service
curl --fail http://127.0.0.1:8765/
curl --fail http://127.0.0.1:8766/status
systemctl --user restart media-bridge-web.service media-bridge-data.service
systemctl --user stop media-bridge-web.service media-bridge-data.service
systemctl --user start media-bridge-web.service media-bridge-data.service
```

자동 시작까지 해제하려면 다음을 실행합니다.

```bash
systemctl --user disable media-bridge-web.service media-bridge-data.service
```

로그 확인:

```bash
journalctl --user -u media-bridge-web.service -u media-bridge-data.service --since "10 minutes ago" --no-pager
```

## 7. 업데이트·되돌리기

업데이트:

```bash
systemctl --user stop media-bridge-web.service media-bridge-data.service
VERSION=0.2.0
ARCH=amd64
sudo dpkg -i "./media-bridge_${VERSION}_${ARCH}.deb"
systemctl --user daemon-reload
systemctl --user start media-bridge-web.service media-bridge-data.service
dpkg-query -W -f "Version: \${Version}\n" media-bridge
```

문제가 생기면 같은 방법으로 이전 package를 다시 설치합니다.

```bash
systemctl --user stop media-bridge-web.service media-bridge-data.service
VERSION=0.1.0
ARCH=amd64
sudo dpkg -i "./media-bridge_${VERSION}_${ARCH}.deb"
systemctl --user daemon-reload
systemctl --user start media-bridge-web.service media-bridge-data.service
```

## 8. 제거

```bash
systemctl --user disable --now media-bridge-web.service media-bridge-data.service
systemctl --user daemon-reload
sudo dpkg -P media-bridge
```

설정과 local state까지 삭제하려면 필요한 backup을 먼저 만든 뒤 정확한 디렉터리만 삭제합니다.

```bash
rm -rf -- "$HOME/.media-bridge"
```

제거 확인:

```bash
dpkg-query -W media-bridge 2>/dev/null || true
ss -ltn | grep -E ":8765|:8766" || true
systemctl --user is-enabled media-bridge-web.service 2>/dev/null || true
systemctl --user is-enabled media-bridge-data.service 2>/dev/null || true
```

package가 없고 두 service가 중지 또는 비활성 상태이며 8765·8766 listener가 없으면 제거가
끝난 것입니다.

## 9. 문제 해결

- Web이 열리지 않으면 Web service를 재시작하고 `status`와 `journalctl`을 확인합니다.
- Data 상태가 정상이 아니면 Data service를 재시작합니다.
- 설정 저장이 거부되면 endpoint 형식, model ID, RPM·TPM 정수값을 확인합니다.
- 화면 인식이 차단되면 화면을 확대하거나 오류 영역을 다시 캡처합니다.
- 업데이트 후 문제가 생기면 6절의 이전 package 되돌리기를 실행합니다.

과거 Compose·PostgreSQL 시험 파일은 이 설치 절차의 선행 조건이 아닙니다.
