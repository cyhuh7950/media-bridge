# Windows에서 Media Bridge 설치·중지·제거

이 문서는 Windows 설치 파일을 받은 뒤 수행할 사용자 절차입니다. 이번 QA 파일은
`Media-Bridge-0.1.0-x64.msi`입니다.

## 1. 설치

1. [GitHub Release v0.1.0](https://github.com/cyhuh7950/media-bridge/releases/tag/v0.1.0)에서
   `Media-Bridge-0.1.0-x64.msi`를 다운로드합니다.
2. 파일을 마우스 오른쪽 버튼으로 클릭합니다.
3. 설치를 선택하고 사용자 폴더를 확인합니다.
4. 설치가 끝나면 시작 메뉴에서 Media Bridge를 실행합니다.
5. 브라우저에서 `http://127.0.0.1:8765/`를 엽니다.

## 2. 최초 설정

OpenCodex endpoint, Solar endpoint, 정확한 model ID, credential 환경변수 이름 또는 OS credential
reference 이름을 입력합니다. key 원문은 입력하지 않습니다. 저장 후 페이지를 새로고침합니다.

## 3. 중지·재시작

작업 표시줄의 Media Bridge 아이콘 메뉴에서 중지 또는 다시 시작을 선택합니다. 브라우저에서
`http://127.0.0.1:8765/`와 `http://127.0.0.1:8766/status`를 다시 확인합니다.

## 4. 제거

Windows 설정 → 앱 → 설치된 앱 → Media Bridge → 제거를 선택합니다. 설정을 남길지 묻는 경우,
다시 사용할 계획이 있으면 보존하고 완전히 삭제할 때만 삭제를 선택합니다.

설치 파일이 서명되지 않은 QA 파일이면 Windows 경고가 표시될 수 있습니다. QA 파일을 공식 배포 파일로
간주하지 않습니다.
