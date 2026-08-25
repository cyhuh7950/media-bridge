# Windows WSL에서 Media Bridge 준비

WSL 설치·port·방화벽·reverse proxy 변경은 자동화하지 않는다. Docker Desktop 또는 WSL 내부
Docker의 volume/UID 동작을 먼저 확인하고, Secret은 Windows 공유 폴더가 아닌 권한을 통제할 수
있는 Linux 경로에 둔다. Docker Compose 설치 절차를 따르되 Windows 경로를 Media Bridge의
local-path 입력으로 전달하지 않는다. 다른 PC HTTPS와 PCWSL Adapter 연결은 아직 미검증이다.
