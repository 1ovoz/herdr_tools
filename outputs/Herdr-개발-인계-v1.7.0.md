# Herdr 플러그인 개발 인계 · Windows x64 v1.7.0

2026-11-26 기준. 다른 컴퓨터에서 개발을 이어가려면 `Herdr-Mod-Kit-Dev-v1.7.0.zip` 하나를 복사해 압축을 풀고 `Herdr-Mod-Kit-Dev` 폴더를 작업 공간으로 여세요. 이 문서, 수정할 원본, 테스트, 설치 도구, 완성된 Windows 설치 ZIP이 들어 있습니다.

## v1.7.0 변경 사항

보안·리소스·속도 점검에서 나온 수정을 반영했습니다. 항목별 내용과 측정값은 [v1.7.0에 적용한 변경](docs/changes-v1.7.0.md)에 있습니다.

- 전송은 4 MiB 조각을 4개씩 동시에 보냅니다. 긴 전송은 도우미를 여러 번 불러 이어 보내고, 작업 창에서 취소하거나 끊긴 곳부터 다시 시도할 수 있습니다. 서버에 올린 파일은 계정 기본 권한을 받습니다.
- PDF는 필요한 페이지를 한 번에 렌더링하고 두 쪽을 미리 읽습니다. 지나간 페이지를 기억하며, 실패한 페이지는 세 번만 다시 시도합니다.
- Files는 변경된 폴더만 다시 읽고, 숨겨진 동안에는 읽지 않습니다. 저장소 자체 설정에 filter가 있으면 Git 표시를 끄고 안내 줄을 보여 줍니다.
- 원격 도우미와 사용량 수집기를 `python -I`로 실행합니다.

이 판은 리눅스에서 빌드하고 테스트했습니다. Windows의 Herdr 앱에서는 아직 실행하지 않았으므로 아래 순서로 확인하세요.

1. 설치 ZIP으로 설치하고 `Diagnose-Windows.cmd`로 모드가 로드되는지 봅니다. 바뀐 JavaScript는 리눅스에서 가짜 API로만 실행했습니다. 설치기는 모드가 로드되지 않으면 기존 설치를 바꾸지 않고 멈춥니다.
2. `verify.py "$qa/profile" --machine lab`으로 SSH 경유 병렬 전송과 업로드 권한을 확인합니다. 4개 동시 전송은 `hc exec` 왕복에서만 측정했습니다.
3. `check-upgrade.py`로 v1.6.0에서 올라오는 업데이트를 확인합니다.
4. `check-speed.py 이전설치.zip`으로 속도를 다시 잽니다.
5. 200쪽 이상 PDF를 넘기고 확대하면서 `herdr-app.exe`의 메모리를 봅니다. `check-resources.py`는 도우미 프로세스만 잽니다.

로컬 Windows 폴더 목록은 여전히 폴더마다 PowerShell을 한 번씩 띄웁니다. `git`은 이름으로 실행합니다.

## v1.6.0 변경 사항

- Files 헤더의 **Refresh** 또는 파일 목록의 `F5`로 현재 루트와 펼친 폴더를 다시 읽습니다. 한 번 클릭해 파일을 선택한 뒤 `Del`을 누르면 그 파일의 삭제 확인창이 열립니다. 더블클릭이나 `Enter`로 파일을 엽니다.
- 분할한 문서 창마다 파일 탭 줄이 있습니다. Files에서 연 파일은 마지막으로 작업한 창에 추가됩니다. 같은 작업 공간에서 같은 머신·경로의 파일을 다시 열면 기존 탭으로 이동합니다. 터미널만 있는 창에서 처음 파일을 열면 그 터미널 옆에 문서 창이 생깁니다. 파일 탭의 ×는 그 파일 하나를 닫습니다.
- 상단 **Layout**에서 활성 창을 좌우 또는 상하로 나눕니다. **Single pane view**로 현재 창을 크게 보고 **Restore split view**로 돌아갈 수 있습니다.
- 이름 변경, 삭제, 전송 오류 및 덮어쓰기 확인창은 취소·실행 버튼을 오른쪽 아래에 정렬합니다.

## v1.5.0 변경 사항

- 하단바 오른쪽에 설치된 모드 버전을 작게 표시합니다. 사용량 기능을 꺼도 다른 기능을 사용하는 기본 레이아웃에서 버전을 확인할 수 있습니다.
- Files에서 파일을 끄는 동안 포인터 옆에 파일명을 표시하고, 현재 드롭할 폴더나 루트 영역을 강조합니다.
- 사용량 팝업의 **Sources**에서 Codex와 Claude Code의 조회 머신을 따로 선택할 수 있습니다. 선택은 이 Herdr 프로필에 저장됩니다. 기존 설치의 공통 머신을 쓰려면 **Install default**를 선택하세요.

## 새 컴퓨터에서 시작

1. Windows x64에 Herdr 데스크톱, herdr-core, Python 3.10 이상(x64)을 준비합니다. Herdr를 한 번 열어 기본 레이아웃을 생성합니다. v1.6.0까지 Herdr 데스크톱 0.1.17에서 검증했습니다. JavaScript 테스트에는 Node.js가 필요합니다. 검증한 버전은 24입니다.
2. `outputs/Herdr-Mod-Kit-Windows-x64-v1.7.0.zip`을 별도 폴더에 풀고 `Herdr-Mod-Kit/Install-Windows.cmd`를 실행합니다. 필요하면 Herdr의 **Settings → Look**에서 `herdr-mod-kit`을 선택합니다. 같은 폴더의 `Diagnose-Windows.cmd`가 기능별 검사 결과를 보여 줍니다.
3. 이 Windows PC에서는 사용량 대상을 `local`로 지정했습니다. 다른 PC에서 원격 서버 사용량이 필요하면 Herdr Machines에 연결한 머신 이름을 사용하세요. 최초 설치 기본값은 `local`이며 업데이트할 때는 기존 대상을 보존합니다.
4. 이 체크아웃의 변경을 Windows에서 실행하려면 저장소 루트에서 아래 명령을 사용합니다. 첫 줄은 설치에 필요한 모드 소스를 준비합니다. 마지막 줄은 실행 중인 Herdr와 설치 파일을 검사합니다.

```powershell
py -3 -X utf8 work/kit-tools/stage.py
py -3 -X utf8 work/herdr-mod-kit/kit.py install --usage-machine local --activate
py -3 -X utf8 work/herdr-mod-kit/kit.py diagnose
```

## Files 우클릭 메뉴

개발 원본과 이 PC의 설치본에는 파일 대상 메뉴 8개와 폴더·루트 붙여넣기가 있습니다. 단축키와 사용 화면은 [프로젝트 README](README.md)에 정리했습니다. 파일 메뉴 원본은 `work/personal-files/main.js`, 파일 작업은 `bridge.py`, 기능별 설치 변환은 `work/kit-tools/stage.py`입니다. 동봉된 설치 ZIP에는 우클릭 메뉴와 포인터 기준 PDF 확대·축소가 포함되어 있습니다.

같은 Windows 체크아웃에서 다른 PC로 개발을 이어가는 방법은 [WSL 원격 개발 안내](docs/remote-work.md)를 참고하세요. 설치 파일을 만들어 달라는 요청이 오면 새 설치본과 인계본을 검증하고, 그 시점에 소스·스크린샷·배포 파일을 함께 GitHub에 갱신합니다.

## 현재 배포에 들어간 기능

| 기능과 로그 | 포함된 동작 | 먼저 볼 원본 |
| --- | --- | --- |
| `usage` · `usage.jsonl` | 상태표시줄 오른쪽의 파란 Codex 막대, Claude 주황 계열 W와 Fable F 막대, 영어 초기화 시간. Fable 별도 한도가 있을 때 표시. Claude 요청 제한 시 이전 값을 유지하고 재조회 간격을 늘림 | `work/lab-usage/main.js`, `collect.py` |
| `transfer` · `transfer.jsonl` | 외부 파일을 Files로 드롭해 업로드, 우클릭 다운로드, Files 안에서 파일 하나를 폴더 행이나 루트 드롭 영역으로 이동. 이동 대상에 같은 이름이 있으면 둘 다 보존. Windows가 진행률 파일을 잠가도 전송을 계속함 | `work/personal-files/main.js`의 `renderMenu`, `rows`, `finishFileDrag`와 같은 폴더의 `bridge.py` |
| `pdf` · `pdf.jsonl` | PDF·텍스트를 탭 또는 좌우 분할로 열기, PDF 연속 세로 스크롤, 텍스트 선택·복사, 열린 파일 자동 갱신, Herdr에 전달된 파일 링크를 Ctrl+클릭으로 열기 | `work/personal-files/document-view.js`, `document-flow.js`, `document-drag.js`, `pdf-geometry.js`, `work/personal-terminal-links/link.js` |
| `tabs` · `tabs.jsonl` | 분할 창 제목을 탭 줄로 드래그해 독립 탭으로 이동. 배포 레이아웃에서 Ctrl+W로 활성 탭 닫기. 기존 키 설정을 발견하면 보존 | `work/personal-pane/main.js`, `work/personal-tabs/main.js`, `work/herdr-mod-kit/kit.py` |

폴더 간 드래그 이동은 같은 머신과 파일시스템의 개별 파일을 대상으로 합니다. 스캔된 PDF에는 선택할 텍스트 레이어가 없을 수 있습니다. Codex 자체 편집기가 숨긴 링크 대상은 Herdr까지 전달되지 않을 수 있어, 그 경우 터미널에 표시한 전체 `file:///…` 주소를 사용합니다. macOS는 PDFium 바이너리, 파일 열기, 드롭과 설치를 실제 Mac에서 검증한 뒤 진행할 항목입니다.

## 수정과 배포

- 기능은 위 표의 원본에서 수정합니다. `work/kit-tools/stage.py`가 원본을 배포용 모드 이름과 기능 선택 조건에 맞춰 변환합니다. Files 메뉴나 드래그 코드가 달라졌을 때 변환기가 알려 주는 코드 조각을 확인하세요. 변환 대상이 사라지면 빌드가 중단됩니다.
- 설치·레이아웃·키 설정·진단은 `work/herdr-mod-kit/kit.py`가 담당합니다. 공용 로그는 `common/kit_log.py`에 있습니다. 공용 전송·문서 도우미는 설치 ZIP의 `common/`에 한 번 묶고, 설치할 때 Herdr JS 로더가 요구하는 모드에 복사합니다.
- 기능을 수정한 뒤에는 작업 폴더에서 테스트하고, 사용자가 설치 파일 반영을 요청한 시점에만 배포본을 만듭니다. 이번 파일명은 v1.7.0이고 설치 기록과 진단에 표시되는 내부 버전은 1.7.0입니다. 기존 배포 이력은 `work/package-publish-notes.md`에 있습니다.

다음 명령은 개발 ZIP을 푼 루트에서 실행합니다. `py`가 없는 환경에서는 `py -3`을 `python`으로 바꿉니다.

```powershell
py -3 -X utf8 -m unittest discover -s work/personal-files -p "test_*.py"
py -3 -X utf8 -m unittest discover -s work/lab-usage -p "test_*.py"
node work/personal-files/test_ui.mjs
node work/personal-files/test_pdf_ui.mjs
node work/personal-files/test_flow.mjs
node work/personal-files/test_groups.mjs
node work/personal-tabs/test_layout.mjs
node work/lab-usage/test_sources.mjs
py -3 -X utf8 work/kit-tools/check-layout.py
py -3 -X utf8 -m unittest discover -s work/kit-tools -p "test_*.py"
```

개발 모드를 스테이징한 뒤 `py -3 -X utf8 work/kit-tools/check-file-actions.py`로 실제 변환된 도우미의 한글 파일 복사, 이름 충돌, 이동, 이름 변경과 삭제 확인을 검사합니다.

배포 요청을 받으면 아래 순서로 실행합니다. 첫 줄은 배포용 소스를 만들고 두 번째는 설치 ZIP을 만듭니다. 마지막 줄은 소스와 설치 ZIP을 담은 개발 인계본을 만듭니다.

```powershell
py -3 -X utf8 work/kit-tools/stage.py
py -3 -X utf8 work/kit-tools/release.py
py -3 -X utf8 work/kit-tools/handoff.py
```

### 설치 ZIP 검사

Linux에서는 설치 ZIP의 무결성과 플랫폼 공통 동작을 검사할 수 있습니다. 저장소 루트에서 다음 명령을 실행합니다. Windows 파일 잠금 테스트 3개는 Linux에서 자동으로 건너뜁니다. `Install-Windows.cmd`, Windows용 PDFium DLL과 Herdr의 네이티브 UI 검사는 Windows x64에서 실행합니다.

```sh
(cd outputs && sha256sum -c SHA256SUMS)
python3 -B -m unittest discover -s work/kit-tools
python3 -B -m unittest discover -s work/lab-usage
python3 -B work/kit-tools/check-layout.py
node work/personal-files/test_ui.mjs
node work/personal-files/test_pdf_ui.mjs
```

사진과 Markdown은 `pdf` 기능의 문서 뷰어를 공유합니다. 전송의 로컬·원격 파일 작업은 `work/personal-files/file_host.py`에 있습니다. `check-speed.py 이전설치.zip`은 같은 Windows 데스크톱 세션에서 기존 버전과 현재 버전의 속도를 비교합니다. Herdr Core 경유 측정은 같은 PC를 사용합니다. 실제 Markdown·사진 화면과 측정값은 루트 README에 있습니다.

Windows x64 Herdr 0.1.17에서 v1.0(내부 1.3.0), v1.4.0, v1.5.0 설치본을 각각 v1.6.0으로 업데이트한 뒤 재설치했습니다. 세 경우 모두 기존 키 설정·레이아웃·사용량 조회 머신이 보존됐습니다. 이전 ZIP이 있는 경우 `py -3 work/kit-tools/check-upgrade.py 이전설치.zip 최신설치.zip`으로 격리된 프로필에서 재현할 수 있습니다. `py -3 work/kit-tools/check-resources.py`는 같은 Windows 프로세스에서 2000×2500 PDF 비트맵을 32회 새로 렌더링하고 전용 메모리와 핸들을 측정합니다.

사용량 수집기는 고정된 HTTPS 주소로 인증서와 호스트 이름을 검증하고 리디렉션을 거절합니다. 로컬 터미널에서 외부 파일 서버로 향하는 링크를 차단하고, 원격 다운로드에는 지원되는 Windows 볼륨에서 인터넷 보안 영역 표시를 붙입니다. 다운로드 후 자동 열기는 PDF, 일반 텍스트와 일부 이미지에 적용됩니다. PDF 캐시는 최근 10분간 사용한 항목을 보호하고, 오래된 항목을 페이지 이미지 256 MiB·원격 원본 512 MiB 목표에 맞춰 정리합니다. 실행 중 파일의 잠금을 해제할 수 없거나 로컬 수정과 충돌하면 설치기는 오류 경로를 알립니다.

아래 명령은 새 임시 프로필에서 실제 배포 파일을 검사합니다. 현재 사용 중인 레이아웃을 전환하지 않습니다.

```powershell
$qa = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path "$qa/profile/layouts" -Force | Out-Null
Copy-Item work/kit-tools/fixtures/main.json "$qa/profile/layouts/main.json"
Expand-Archive outputs/Herdr-Mod-Kit-Windows-x64-v1.7.0.zip "$qa/install"
py -3 -X utf8 "$qa/install/Herdr-Mod-Kit/kit.py" install --app-home "$qa/profile"
py -3 -X utf8 "$qa/install/Herdr-Mod-Kit/kit.py" diagnose --app-home "$qa/profile"
node work/kit-tools/check-tabs-and-links.cjs "$qa/profile"
```

연결된 Linux 머신에서도 확인하려면 같은 PowerShell 창에서 `py -3 -X utf8 work/kit-tools/verify.py "$qa/profile" --machine lab`을 실행합니다. 동봉한 시험용 PDF를 서버의 고유 임시 폴더에 올려 전송·이동·렌더링·갱신을 확인하고 원격 시험 파일을 정리합니다.

### Herdr 업데이트 뒤 문제가 생길 때

설치 ZIP을 푼 폴더에서 `py -3 -X utf8 kit.py diagnose --features transfer --verbose`처럼 한 기능부터 확인합니다. `transfer` 자리에 `usage`, `pdf`, `tabs`를 넣을 수 있습니다. 기본 로그 폴더는 `%USERPROFILE%\.config\herdr-app\data\herdr-mod-kit\logs`이며, `HERDR_APP_HOME`을 설정하면 그 폴더 아래의 `data/herdr-mod-kit/logs`를 봅니다. 설치·활성화는 `installer.jsonl`, 기능 오류는 위 표의 각 로그에서 찾습니다. `upstream_changed`는 설치 후 Herdr 기본 파일이 바뀌었다는 신호입니다. 실제 로드 오류와 비교해 충돌 지점을 찾으세요.
