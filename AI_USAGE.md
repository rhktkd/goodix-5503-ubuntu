# AI 사용 고지 / AI assistance disclosure

이 프로젝트의 우분투 통합 도구, 로컬 페어링 패치, 테스트, 문서 및 배포 준비는 **OpenAI Codex의 AI 지원을 받아 작성·수정**했습니다.

AI가 수행한 작업에는 설치 파일의 정적 분석·추출 도구 작성, 기존 공개 드라이버와 프로토콜 근거 비교, 우분투 빌드·패키징 도구 작성, GF3208 페어링 검사 보완, 테스트와 문서 작성이 포함됩니다. 기존 드라이버를 AI가 처음부터 독자 개발했다고 주장하지 않습니다.

프로젝트 사용자가 실제 Ubuntu 노트북에서 관리자 명령을 실행하고, 센서 키 교체 확인 문구를 직접 입력했으며, 손가락 등록·`verify-match`·지문 잠금 해제 완료를 확인했습니다. AI가 사용자의 손가락을 대신 등록하거나 잠금 화면을 직접 관찰한 것은 아닙니다.

검증한 환경은 **ThinkBook 14 G3 ACL / Goodix 27c6:5503 / Ubuntu 26.04.1 amd64** 한 조합입니다. 독립 보안 감사, 통계적 오인식률 측정, 다른 센서·배포판에서의 동작 검증은 수행하지 않았습니다. 재부팅·절전 복귀와 다른 손가락 거부의 반복 검증도 별도로 수행하지 않았습니다.

원본 구현과 저작권은 각 upstream 기여자에게 있습니다. 출처·라이선스는 [NOTICE.md](NOTICE.md), 검증 범위는 [docs/VALIDATION.md](docs/VALIDATION.md)에 정리했습니다. AI 사용은 원저작자 표기나 라이선스 의무를 대체하지 않습니다.

---

The Ubuntu integration tooling, local pairing patch, tests, documentation and publication preparation were written and revised with **AI assistance from OpenAI Codex**. This project builds on existing community drivers; it is not an independently authored replacement for all upstream work.

The user ran the privileged commands and explicitly confirmed the sensor pairing change on their own laptop. Enrollment, `verify-match`, and fingerprint unlock were reported by that user. This is one tested hardware/software combination, not an independent security audit or a claim of general compatibility.
