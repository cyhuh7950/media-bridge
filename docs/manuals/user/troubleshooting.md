# Media Bridge 문제 해결

## Media Bridge가 시작되지 않음

```bash
mb status
mb health --json
```

runtime artifact가 없다는 오류가 나오면 현재 플랫폼용 runtime release가 없는
것입니다. Python, Docker 또는 `.deb`를 직접 설치하는 것으로 우회하지 않습니다.

checksum 또는 압축 해제 오류가 나오면 `mb start`를 반복하거나 다른 `tar.exe`를 PATH에 추가하지
말고 오류 문구, OS·아키텍처, npm package version을 기록합니다. 기존 검증 runtime은 보존됩니다.

## 설정이 적용되지 않음

```bash
mb init
mb status --json
```

설정은 `$HOME/.media-bridge/config.json`에 저장됩니다.

## 설정 저장 실패

endpoint에 사용자명·비밀번호·query를 넣지 않습니다. model ID는 실제 제공자가 요구하는 정확한 값을
입력하고 RPM·TPM은 양의 정수로 입력합니다.

## 화면 인식 차단

화면을 확대하고 오류 영역만 다시 캡처합니다. 작은 글씨, 흐림, 잘린 오류 문구를 피하고 필요하면
오류 문구를 직접 입력합니다. 인식이 부족한 화면을 Solar로 우회 전달하지 않습니다.

## 로그 확인

```bash
mb status --json
mb health --json
```

로그와 오류 보고에는 key 원문, 화면 원문, OCR 원문을 넣지 않습니다.
