# 다른 PC에서 WSL로 Herdr 개발하기

다른 PC에서 평소 쓰는 Tailscale SSH 주소로 이 Windows PC의 WSL에 접속합니다. 아래의 `my-wsl`에는 기존 SSH 별칭이나 `WSL사용자@Tailscale장치이름`을 넣으세요.

```sh
ssh my-wsl
cd ~/herdr_tools
git status --short --branch
```

`~/herdr_tools`는 Windows의 `herdr_pj\herdr_tools` 체크아웃을 가리킵니다. 이 디렉터리에서 수정한 파일은 Windows에서도 바로 보입니다. `pwd -P`로 실제 경로를 확인할 수 있습니다. VS Code에서는 **Remote-SSH → Connect to Host**로 같은 WSL에 접속한 뒤 **Open Folder**에서 `~/herdr_tools`를 엽니다.

다른 Windows PC의 Codex에서는 **Settings → Connections → SSH**에서 기존 호스트를 선택하고 이 체크아웃을 프로젝트 폴더로 여세요. 터미널에서는 접속 후 `cd ~/herdr_tools && codex`로 시작할 수 있습니다. [OpenAI 원격 연결 안내](https://learn.chatgpt.com/docs/remote-connections)

## 같은 Windows Codex 대화 이어가기

이 PC에 열려 있는 기존 대화는 Windows 데스크톱 호스트의 기기 연결을 사용합니다. 호스트의 Codex에서 **Settings → Connections → Control this PC**를 열어 연결을 허용하고, 다른 PC의 Codex에서는 같은 계정·워크스페이스로 **Settings → Connections → Control other devices**에서 이 호스트를 선택합니다. 처음 연결하는 기기는 양쪽 앱에 표시되는 페어링과 본인 확인을 완료한 뒤 호스트의 대화 목록에서 기존 제목을 선택합니다. 원격 작업 중에는 호스트 PC와 데스크톱 앱이 실행 중이어야 합니다. [OpenAI 기기 연결 안내](https://learn.chatgpt.com/docs/remote-connections#pick-up-work-from-another-device)

## 원격 셸에서 확인하기

저장소 루트에서 WSL Python으로 사용량 수집기 단위 테스트를 실행합니다.

```sh
python3 -B -m unittest discover -s work/lab-usage -p 'test_*.py'
```

Windows에 설치된 Herdr와 모드를 검사하려면 다음 명령을 실행합니다. 이 PC에서 실행 중인 Windows용 herdr-core가 Windows Python으로 현재 체크아웃의 진단 명령을 실행합니다. SSH로 접속한 WSL 셸에서도 Herdr 데스크톱 세션을 사용해 모드를 검사할 수 있습니다.

```sh
sh work/kit-tools/windows-kit.sh diagnose
sh work/kit-tools/windows-kit.sh diagnose --features usage --verbose
```

다른 PC에서 한 번만 실행하려면 `ssh my-wsl 'cd ~/herdr_tools && sh work/kit-tools/windows-kit.sh diagnose'`를 사용합니다. `disabled or not installed`는 해당 기능의 설치를 먼저 확인해야 한다는 뜻입니다. 실제 메뉴 조작과 상태 표시줄은 이 Windows PC의 Herdr 창에서 확인합니다.

수정한 소스를 이 Windows PC의 Herdr에 적용하려면 아래 명령을 실행하세요. 개발 모드들을 준비해 설치하며 현재 작업 폴더와 연결된 Herdr 레이아웃을 활성화합니다.

```sh
sh work/kit-tools/windows-kit.sh install --usage-machine local --activate
```
