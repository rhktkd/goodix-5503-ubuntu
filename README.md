# Goodix 5503 Ubuntu integration

**AI 사용 고지:** 이 프로젝트의 통합 코드·패치·테스트·문서는 OpenAI Codex의 AI 지원을 받아 작성했습니다. 기존 커뮤니티 드라이버를 기반으로 하며, AI가 원본 드라이버를 독자 개발했다고 주장하지 않습니다. [AI 사용 범위와 사람의 검증](AI_USAGE.md) · [출처와 라이선스](NOTICE.md)

Goodix USB **`27c6:5503`** 지문 센서를 Ubuntu의 `libfprint` / `fprintd`에 연결하는 실험용 통합 도구입니다. **ThinkBook 14 G3 ACL / Ubuntu 26.04.1 amd64**에서 설치·페어링·등록·`verify-match`·지문 잠금 해제까지 사용자가 확인했습니다. [검증 범위와 한계](docs/VALIDATION.md)

This is an **AI-assisted** Ubuntu integration of the existing [Goodix 5503 community driver](https://github.com/Duro02/goodix-5503-linux), with a recorded local pairing patch. It is not an official Lenovo/Goodix driver or an independently audited biometric product.

## 지원 범위

- USB `27c6:5503`만 대상으로 합니다. ELAN, Synaptics, `550a` 등 다른 장치를 지원한다고 주장하지 않습니다.
- APP 이름은 `GF3258_RTSEC_APP_10063` 또는 `GF3208_RTSEC_APP_10063`, IAP는 `MILAN_RTSEC_IAP_10027`로 제한합니다.
- 새 키 쓰기 직전 고정 MCU 리셋과 DN2 chip-ID **`0x220f`**, APP/IAP, 기존 R 검증값 불변성을 확인합니다. 다른 프로파일이면 쓰기 전에 중단합니다.
- Ubuntu 22.04/24.04와 재부팅·절전 복귀, 다른 손가락 거부의 반복 검증은 수행하지 않았습니다.

## 설치·빌드

일반 데스크톱 사용자 터미널에서 실행하세요. 스크립트 전체를 `sudo`로 실행하지 않습니다. 관리자 작업만 내부에서 `sudo`를 요청합니다.

```bash
git clone https://github.com/rhktkd/goodix-5503-ubuntu.git
cd goodix-5503-ubuntu
python3 ubuntu-goodix5503.py deps
mkdir -p 자료
curl --fail --location https://download.lenovo.com/consumer/mobiles/74ti05afkkxbyyb0.exe -o 자료/74ti05afkkxbyyb0.exe
python3 ubuntu-goodix5503.py prepare --download-encoder
python3 ubuntu-goodix5503.py probe
python3 ubuntu-goodix5503.py build
python3 ubuntu-goodix5503.py package
```

`prepare`는 `sources.lock.json`의 커밋을 내려받고, 원본 해시를 확인한 뒤 기록된 로컬 페어링 패치를 자동 적용합니다. Windows 설치 프로그램은 실행하지 않습니다. 빌드와 오프라인 테스트·동적 링크 검사에 성공해야 패키지를 생성합니다. 출력된 DEB 경로를 사용해 설치하세요. 현재 고정 버전의 예시는 다음과 같습니다.

```bash
sudo apt install ./dist/libfprint-goodix5503-isolated_0.1+gitc7c22acb8e_amd64.deb
```

패키지는 별도 `/opt/goodix5503/lib`와 fprintd용 systemd 설정을 사용합니다. 우분투 기본 libfprint 패키지는 보존하며, 패키지 설치만으로 센서 키나 PAM을 변경하지 않습니다. 바이너리는 빌드한 OS의 라이브러리에 의존합니다.

이미 준비된 환경에서는 `python3 ubuntu-goodix5503.py continue --install --skip-deps --download-encoder`로 준비·센서 확인·빌드·설치를 이어갈 수 있습니다. 실패 단계는 로컬 `evidence/continuation.json`에 기록합니다.

## 최초 페어링과 등록

**새 페어링은 센서 PSK를 변경하여 기존 Windows 지문 등록을 무효화합니다. 백업만으로 원래 키 전체를 복원할 수 있다고 보장하지 않습니다.** 이 변경을 수락할 때만 도구의 확인 문구 `REPLACE WINDOWS PAIRING`을 입력하세요. 이미 키가 일치하면 쓰기 없이 종료합니다.

```bash
python3 ubuntu-goodix5503.py pair
```

`pairing-ready` 또는 `already-paired-no-write`를 확인한 뒤 진행합니다.

```bash
fprintd-enroll -f right-index-finger "$USER"
fprintd-verify -f right-index-finger "$USER"
```

등록한 손가락으로 `verify-match`를 확인한 뒤 로그인에 연결합니다.

```bash
sudo pam-auth-update --enable fprintd
```

`Super+L`로 잠근 뒤 지문 잠금 해제를 확인하세요. 비밀번호 인증도 유지됩니다. 쓰기 결과가 불명확하다는 오류가 나면 준비 키·백업을 삭제하거나 새 키로 바꿔 반복하지 마세요.

## 제거

```bash
sudo apt remove libfprint-goodix5503-isolated
sudo pam-auth-update --disable fprintd
```

패키지 제거는 전용 라이브러리·systemd 설정을 제거합니다. **센서 PSK나 Windows 등록을 복원하지 않습니다.** 로컬 키·백업·등록 템플릿은 자동으로 삭제하지 않습니다.

## 공개 파일과 테스트

이 저장소에는 통합 코드·패치·테스트·문서만 포함합니다. Windows 바이너리, 센서 키, 원래 페어링 백업, 지문 이미지·템플릿, 로컬 로그·장치 상태 파일은 포함하지 않습니다. 비밀 파일을 이슈에 첨부하지 마세요.

- [검증 결과와 테스트 실행](docs/VALIDATION.md)
- [고정 아티팩트 해시](docs/ARTIFACTS.md)
- [AI 사용 고지](AI_USAGE.md)
- [원저작자·라이선스](NOTICE.md)

원본 통합 코드와 로컬 패치는 **LGPL-2.1-or-later**, 추출기는 파일에 보존된 zlib-style 라이선스를 따릅니다. [LICENSE](LICENSE)
