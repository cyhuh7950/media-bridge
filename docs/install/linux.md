# Linux에서 Media Bridge 준비

전용 비루트 운영 계정, 충분한 PostgreSQL volume, UTC/NTP, Secret backup 제외 정책을 준비한다.
`deploy/compose.yaml`의 base digest와 `deploy/versions.env`를 검토하고 Docker Compose 가이드를
따른다. 현재 검증은 ysna-server의 격리 project/volume에서 수행했으며 clean Linux VM 설치는
별도 미검증이다. systemd, host port, firewall은 이 bundle이 변경하지 않는다.
