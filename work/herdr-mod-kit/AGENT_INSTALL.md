# Herdr Mod Kit Windows x64 v1.9.0 설치·진단 인계

이 문서와 함께 `Herdr-Mod-Kit-Windows-x64-v1.9.0.zip`을 제공하세요. 설치 진단에는 내부 버전 1.9.0으로 표시됩니다. Codex 또는 파일을 읽고 명령을 실행할 수 있는 GPT 에이전트에 아래 요청을 전달하면 됩니다.

> 첨부한 Herdr Mod Kit ZIP을 Windows x64 PC에 설치해줘. 압축을 풀고 README와 kit.py를 읽어 설치 대상과 사용 가능 기능을 확인해줘. Herdr 데스크톱 0.1.17 이상과 Python이 있다면 먼저 탐지해줘. 기존 키 설정을 보존하고, 패키지 설치 후 `diagnose`로 사용량·파일 전송·PDF·탭 검사 결과를 기능별로 알려줘. 이전 설치의 사용량 대상과 기능 선택을 보존해줘. 최초 설치는 로컬 사용량을 사용해줘. 토큰이나 원격 로그인 파일은 채팅이나 진단 출력에 포함하지 마.

전체 기본 설치 명령은 아래와 같습니다. `py`가 없다면 `python`으로 대체합니다.

```powershell
py -3 -X utf8 .\kit.py install --activate
py -3 -X utf8 .\kit.py diagnose
```

Herdr 앱을 한 번 실행해 기본 레이아웃을 생성해야 합니다. 옵션과 테스트 대안은 ZIP 내부 `README.md`를 참고하세요. 앱 업데이트 뒤 문제가 생겼다면 `diagnose --features usage`, `diagnose --features transfer`, `diagnose --features pdf`, `diagnose --features tabs`를 각각 실행합니다. 실패한 네이티브 검사의 자세한 오류는 `--verbose`로 확인할 수 있습니다. Mac 설치는 별도 검증 후 진행합니다.
