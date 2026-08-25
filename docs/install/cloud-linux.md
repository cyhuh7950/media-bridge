# Cloud Linux에서 Media Bridge 준비

Media Bridge DB를 public subnet이나 public port에 노출하지 않는다. Control/Data ingress와 provider
egress를 분리하고, cloud Secret Store는 값이 아니라 file/reference 주입 경계로 연결한다. TLS 종료,
load balancer health, backup object retention은 해당 cloud의 승인된 운영 설계가 필요하다. 실제 cloud
Linux와 managed PostgreSQL은 아직 검증되지 않았다.
