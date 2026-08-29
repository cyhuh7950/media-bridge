# Linux에서 Media Bridge 준비

개인용 제품은 기존 개발·staging Compose나 외부 DB를 준비하지 않고 native `.deb`와 user-level
systemd service로 실행한다. Web과 Data는 loopback에만 열리며 설정은 Web UI에서 수행한다.
설치 전에는 package checksum과 출처만 확인하고, API key 원문 대신 환경변수 또는 OS credential
reference를 사용한다. systemd, host port, firewall은 이 bundle이 변경하지 않는다.

## 개인용 Linux 패키지 경계 (현재 제품 경로)

위의 Compose/PostgreSQL 내용은 개발·staging 보조 경로의 역사적 기록이다. 개인용 제품은
Ubuntu/Debian amd64용 `QA/UNSIGNED` `.deb`를 사용하며, 일반 사용자는 Docker, PostgreSQL,
Redis, Python 또는 Node를 설치하지 않는다. 공식 서명·배포 저장소가 없는 산출물은 제품
release로 취급하지 않는다.

QA 실행 순서는 다음과 같다(실제 설치 전 package checksum과 출처를 확인한다).

```text
dpkg-deb --info media-bridge_<version>_amd64.deb
sudo dpkg -i media-bridge_<version>_amd64.deb
systemctl --user enable --now media-bridge-web.service media-bridge-data.service
xdg-open http://127.0.0.1:8765/
```

설정은 loopback Web UI에서 수행하고, Solar API key 원문 대신 환경변수 또는 OS credential
reference만 등록한다. 중지·해제는 `systemctl --user disable --now ...` 후 package manager의
일반 제거 절차를 사용한다. 실제 ysna clean-install은 별도 인수시험 전까지 미검증이다.
