# Media Bridge 관리 매뉴얼

## 시작·중지

```bash
systemctl --user enable --now media-bridge-web.service media-bridge-data.service
systemctl --user stop media-bridge-web.service media-bridge-data.service
systemctl --user restart media-bridge-web.service media-bridge-data.service
```

## 상태 확인

```bash
systemctl --user --no-pager status media-bridge-web.service media-bridge-data.service
curl --fail http://127.0.0.1:8765/
curl --fail http://127.0.0.1:8766/status
```

## 로그 확인

```bash
journalctl --user -u media-bridge-web.service -u media-bridge-data.service --since "10 minutes ago" --no-pager
```

설정은 Web 화면에서 변경합니다. key 원문, 화면 원문, 요청 본문을 로그나 문서에 복사하지 않습니다.
