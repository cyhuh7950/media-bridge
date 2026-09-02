# Media Bridge CLI

이 패키지는 Media Bridge의 설치 후 실행·상태 확인·설정 진입점을 제공합니다.

```bash
npm install -g @bitkyc08/media-bridge
mb init
mb start
```

현재 실행기는 관리된 Media Bridge runtime을 사용합니다. 지원 플랫폼용 runtime
artifact가 없는 경우에는 사용자에게 Python, Docker 또는 `.deb` 설치를 요구하지 않고
설치 불가 사유를 표시합니다.
