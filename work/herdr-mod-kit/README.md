# Herdr Mod Kit · Windows x64 v1.8.0

Windows x64용 Herdr 데스크톱 모드입니다. 사용량 표시, 파일 전송, PDF 뷰어, 탭 관리를 함께 설치하거나 골라서 사용할 수 있습니다. 배포 파일명은 v1.8.0이며, 기존 설치를 구분하는 내부 버전은 1.8.0입니다.

## 새 Windows PC에 설치하기

1. [Herdr 데스크톱](https://herdr.dev/download/) 0.1.17 이상과 [Windows x64 Python](https://www.python.org/downloads/windows/) 3.10 이상을 준비합니다. Herdr를 한 번 실행해 기본 레이아웃을 생성합니다. 파일 전송과 원격 PDF 읽기는 `herdr-core`가 필요합니다.
2. ZIP 압축을 전부 푼 뒤 `Install-Windows.cmd`를 실행합니다. 실행 중인 Herdr가 있으면 `herdr-mod-kit` 레이아웃이 바로 활성화됩니다. Herdr가 닫혀 있으면 앱을 열고 Settings > Look에서 해당 레이아웃을 선택합니다.
3. 최초 설치의 기본 사용량 대상은 로컬 Windows입니다. 업그레이드 시 기존 기능과 사용량 머신을 유지합니다. 원격 사용량을 조회하려면 새 PC의 Herdr Machines에 `lab`을 연결합니다. 표시 이름이 다르면 아래 명령에서 `my-server`를 바꿉니다. 같은 서버라도 새 PC의 Herdr 연결은 별도로 등록해야 합니다.

```powershell
py -3 -X utf8 .\kit.py install --usage-machine my-server --activate
```

`py`가 없는 PC에서는 `python`을 사용합니다. Windows에 Codex·Claude Code를 직접 로그인해 사용하는 경우 `--usage-machine local`을 지정할 수 있습니다. 원격 조회는 해당 머신의 `python3` 및 두 CLI의 구독 로그인 파일이 필요합니다. Fable은 계정에서 별도 한도를 제공하는 경우에 표시됩니다. 로그인 파일이나 원격 연결 정보는 ZIP에 들어 있지 않습니다.

업데이트가 적용되면 하단바 오른쪽에 `mod 1.8.0`이 보입니다. 사용량 막대를 눌러 **Sources**를 열고, Codex와 Claude Code가 읽을 머신을 각각 고르세요. 예를 들어 Codex는 **local**, Claude Code는 기존 Herdr 머신 **lab**을 선택할 수 있습니다. **Install default**는 설치 당시 공통 대상을 사용합니다.

## 기능

Files에서 폴더나 목록 빈 곳을 우클릭하면 **New File…**과 **New Folder…**로 그 위치에 파일과 폴더를 만듭니다. **Download as ZIP…**을 누르면 선택한 폴더를 ZIP으로 묶어 Windows에서 고른 위치에 저장합니다.

Files에서 파일을 한 번 클릭하면 선택하고, 더블클릭이나 `Enter`를 누르면 마지막으로 사용한 문서 창에서 엽니다. 같은 작업 공간에서 이미 열린 파일은 기존 탭으로 이동합니다. 상단 **Layout**에서 좌우·상하로 분할하면 각 문서 창에 파일 탭 줄이 생깁니다. 터미널만 있는 창에서는 첫 파일을 터미널 옆에 엽니다. **Refresh** 또는 목록의 `F5`로 펼친 폴더까지 새로 읽습니다. 선택한 파일에서 `Del`을 누르면 삭제 확인창이 열립니다.

PNG·JPEG와 Markdown 파일도 문서 탭에서 열립니다. 사진은 창에 맞게 표시되며 PNG 투명도와 JPEG 방향 정보를 지원합니다. Markdown은 제목, 표, 목록, 코드 블록을 읽기 화면으로 표시하며 Source 버튼으로 원문을 볼 수 있습니다. Ctrl+Enter로 오른쪽 분할에 엽니다.

| 기능 | 동작 | 코드 | 로그 |
| --- | --- | --- | --- |
| `usage` | 오른쪽에 Codex 막대와 Claude `W`·`F` 두 줄, 사용률과 초기화까지 남은 시간 표시 | `mods/herdr-kit-usage/` | `usage.jsonl` |
| `transfer` | Files에 파일 드롭, 폴더 간 드래그 이동, 우클릭 다운로드·다운로드 후 열기, 전송 시 덮어쓰기 확인, 전송 취소와 이어 보내기 | `mods/herdr-kit-files/` | `transfer.jsonl` |
| `pdf` | 파일 링크를 `Ctrl+클릭`해 PDF·텍스트 탭 열기, PDF·Files 항목을 좌우로 드래그해 분할, Ctrl+휠 확대·축소, 고해상도 렌더링, 연속 세로 스크롤, 파일 자동 갱신, 텍스트 선택 | `mods/herdr-kit-pdf/`, `mods/herdr-kit-tabs/`, `mods/herdr-kit-links/` | `pdf.jsonl` |
| `tabs` | 상단 Layout으로 좌우·상하 분할과 한 창 확대·복원, 분할 창 제목을 탭 줄에 드롭해 새 탭으로 이동, `Ctrl+W`로 현재 탭 닫기 | `mods/herdr-kit-pane/` | `tabs.jsonl` |

Files에서 파일을 우클릭하면 오른쪽 분할 열기, 잘라내기·복사, 저장 위치를 고르는 다운로드, 전체·상대 경로 복사, 이름 바꾸기와 영구 삭제 확인을 사용할 수 있습니다. 잘라내거나 복사한 파일은 같은 머신의 폴더 행 또는 루트 드롭 영역에 붙여넣습니다. 이름 충돌 시 기존 파일을 보존합니다. 영구 삭제는 선택한 개별 파일에 적용됩니다.

Files 안에서 파일을 끌면 포인터 옆에 파일명이 표시됩니다. 강조된 폴더 행에 놓으면 그 폴더로 이동합니다. Files 상단 드롭 영역에 놓으면 현재 루트 폴더로 이동합니다. 같은 머신과 파일시스템에서 동작하며 목적지에 같은 이름이 있으면 두 파일을 모두 보존합니다. Windows에서 진행률 파일이 잠시 잠겨도 업로드가 계속됩니다.

큰 파일은 여러 번에 나눠 이어 보냅니다. 작업 창의 **Cancel**로 멈출 수 있고, 연결이 끊긴 뒤 **Retry**를 누르면 끊긴 곳부터 이어 갑니다. 서버에 올린 새 파일은 그 계정의 기본 권한을 받고, 덮어쓴 파일은 기존 권한을 유지합니다.

저장소 자체 설정(`.git/config`)에 filter 프로그램이 지정된 폴더에서는 Files가 Git 표시를 계산하지 않고 목록 아래에 안내 줄을 보여 줍니다. 신뢰하는 저장소라면 그 줄을 눌러 표시를 켜세요. 하위 모듈은 커밋이 바뀐 경우에만 표시됩니다.

PDF 페이지가 열리지 않으면 세 번 다시 시도한 뒤 멈춥니다. 페이지를 클릭하거나 확대하면 다시 시도합니다.

Claude 사용량이 HTTP 429를 반환하면 마지막으로 확인한 수치를 표시합니다. 다음 요청은 서버의 `Retry-After`와 재시도 간격 중 더 긴 시간이 지난 뒤에 보냅니다.

파일 업로드는 개별 파일을 지원합니다. PDF 텍스트 선택은 텍스트 레이어가 있는 페이지에서 작동합니다. `pdf`만 켜도 Files에서 탭과 분할 보기를 열 수 있습니다. 업로드와 다운로드에는 `transfer`도 켜야 합니다. PDF 렌더러는 ZIP에 동봉되어 설치 중 `pip install`이 필요하지 않습니다.

Codex가 링크를 자체 편집기에 연결한 경우에는 전체 경로를 일반 텍스트 `file:///…/파일.pdf` 형태로 표시하게 한 뒤 그 주소를 `Ctrl+클릭`합니다. 브라우저 주소는 평소처럼 기본 브라우저에서 열립니다. Herdr는 처음 발견한 링크 모드를 현재 개인 레이아웃에 등록할 수 있습니다. 패키지의 파일 뷰어는 `herdr-mod-kit` 레이아웃에서 동작합니다.

`Ctrl+W`는 `herdr-mod-kit`에서 Herdr 탭 닫기로 동작하므로, 이 레이아웃의 터미널에서는 해당 키를 셸에 전달하는 대신 탭 닫기를 실행합니다. 기존에 같은 키가 설정되어 있으면 그 설정을 유지하고 설치 결과와 `tabs.jsonl`에 기록합니다. 다시 설치하면서 `tabs`를 제외하면 설치 프로그램이 추가한 키만 제거합니다.

설치 ZIP의 `common/`에 공용 파일 전송·문서 탐색·로그 코드를 모았습니다. 공용 Python 도우미는 설치 프로필의 `data/herdr-mod-kit/helpers/`에 한 번 설치됩니다. Herdr의 모드별 JavaScript 로더를 위해 필요한 공용 JavaScript만 각 모드에 복사합니다.

## Herdr 업데이트 후 진단

`Diagnose-Windows.cmd`를 실행하거나 한 기능만 지정합니다.

```powershell
py -3 -X utf8 .\kit.py diagnose --features pdf
```

Herdr 검사에서 실패한 코드의 오류 위치를 보려면 `--verbose`를 추가합니다. 이때 터미널 출력에는 로컬 경로가 표시될 수 있습니다.

기본 로그 위치는 `%USERPROFILE%\.config\herdr-app\data\herdr-mod-kit\logs`입니다. `HERDR_APP_HOME`을 설정했다면 해당 폴더를 기준으로 합니다. 각 줄은 UTC 시각, 기능, 단계, 코드, 필요한 경우 작업 ID를 담은 JSON입니다. 문서 내용, 파일 경로, 원격 이름, 토큰은 로그에 쓰지 않습니다. `installer.jsonl`에는 설치·활성화 코드가 기록됩니다.

- `native …=exit_N`은 해당 모드를 Herdr가 로드하지 못했다는 뜻입니다. 새 Herdr 버전과 모드 API부터 비교합니다.
- `upstream_changed`는 Herdr 기본 레이아웃, Files 또는 Tabs가 설치 당시와 달라졌다는 뜻입니다. `diagnose --features`로 관련 모드의 로드와 파일 무결성을 확인할 수 있습니다.
- `helper_unavailable`은 앱 내장 로그 태그 `[herdr-kit/transfer]` 또는 `[herdr-kit/pdf]`로 남습니다. Python이 실행되지 않은 경우 기능 JSONL을 쓸 수 없으므로 진단의 `Python`, `core` 항목을 먼저 봅니다.
- `collector_unreachable`, `http_401`, `http_429`는 상태표시줄 로드 오류와 구별되는 조회 오류입니다. 각각 머신 연결, 재로그인, 요청 제한을 확인합니다.

한 기능을 빼고 다시 설치해 재현 여부를 비교할 수 있습니다. 다음 명령은 PDF를 빼고 사용량과 전송만 활성화합니다.

```powershell
py -3 -X utf8 .\kit.py install --features usage,transfer --activate
```

모든 기능을 명시적으로 활성화하려면 `--features usage,transfer,pdf,tabs`를 사용합니다. 기본 앱으로 돌아가려면 Herdr에서 기존 `main` 레이아웃을 선택합니다. 다시 설치하면 변경되는 패키지 파일은 `data/herdr-mod-kit/backups/`에 백업됩니다. PDF 탭을 이미 열었다면 기능 제외를 확인할 때 해당 탭을 닫고 Files에서 새로 열어 보세요. 설치 프로그램은 사용자 기본 레이아웃이나 원래 Files 모드를 교체하지 않습니다.

## macOS

이번 ZIP의 설치 및 PDF 엔진은 Windows x64용입니다. macOS 배포는 실제 Mac에서 앱 실행 경로, PDFium의 macOS 바이너리, 드롭·다운로드 후 열기, PDF 마우스 선택을 확인한 뒤 진행합니다.

Herdr Files 원본 코드는 Apache 2.0 조건에 따릅니다. 원문은 `licenses/`에 있습니다. PDFium 관련 라이선스는 `mods/herdr-kit-pdf/vendor/pypdfium2-5.15.2.dist-info/licenses/`에 있습니다.
