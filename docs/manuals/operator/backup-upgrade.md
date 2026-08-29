# Media Bridge 업데이트·복구

## 업데이트 전

현재 사용 중인 package와 이전 package 파일을 함께 보관합니다. Web 설정값은 local state에 저장됩니다.

```bash
systemctl --user stop media-bridge-web.service media-bridge-data.service
```

## 업데이트

```bash
sudo dpkg -i ./media-bridge_<새버전>_<아키텍처>.deb
systemctl --user daemon-reload
systemctl --user start media-bridge-web.service media-bridge-data.service
```

Web 화면을 새로 열어 기존 설정을 확인합니다.

## 복구

문제가 생기면 service를 중지하고 이전 package를 다시 설치합니다.

```bash
systemctl --user stop media-bridge-web.service media-bridge-data.service
sudo dpkg -i ./media-bridge_<이전버전>_<아키텍처>.deb
systemctl --user daemon-reload
systemctl --user start media-bridge-web.service media-bridge-data.service
```

복구 후 Web 설정과 `http://127.0.0.1:8766/status`를 확인합니다.
