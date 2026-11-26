# v1.7.0에 적용한 변경

2026-11-26, v1.6.0 대비. 보안·리소스·속도 점검에서 나온 수정을 반영했습니다. 리눅스에서 단위 테스트와 `hc exec` 왕복으로 확인했고, Windows의 Herdr 앱에서는 아직 실행하지 않았습니다. Windows에서 확인할 순서는 [인계 문서](../HANDOFF.md)에 있습니다.

## 전송

| 변경 | 위치 |
| --- | --- |
| 조각을 1 MiB에서 4 MiB로 키우고 4개를 동시에 보냅니다. 올릴 때는 조각을 각자의 위치에 쓰고 끝에서 전체 해시로 확인합니다. 이 크기가 통하지 않으면 1 MiB 순차, 180 KiB 순차로 내려갑니다. | `bridge.py`의 `CHUNK_STEPS`, `upload_stage`, `download`, `file_host.py`의 `write_at` |
| 도우미 한 번은 180초까지만 보내고 이어받을 위치를 돌려줍니다. 작업 창이 같은 요청에 `resume`을 붙여 다시 부르므로 앱의 10분 제한에 걸리지 않습니다. | `bridge.py`의 `Control`, `main.js`의 `work` |
| 연결이 끊기면 받은 데까지 남겨 두고, **Retry**가 그 위치부터 이어 갑니다. 창을 닫으면 남긴 임시 파일을 지웁니다. | `bridge.py`의 `Failure.resume`, `discard`, `main.js`의 `closeJob` |
| 작업 창에 **Cancel**이 생겼습니다. `jobs/<작업>.cancel` 파일로 도우미에 알리고, 도우미는 조각 사이에서 멈춘 뒤 임시 파일을 지웁니다. | `main.js`의 `cancelJob`, `bridge.py`의 `Control.check` |
| 같은 PC 안의 업로드·다운로드는 조각과 base64 없이 한 번에 복사합니다. | `bridge.py`의 `local_copy`, `local_upload`, `local_download` |
| 내려받을 때 64 MiB가 넘는 파일은 전송 전 해시를 건너뛰고 끝에서 `digest`로 확인합니다. 진행률이 바로 나타납니다. | `file_host.py`의 `stat`, `digest` |
| 원격 미리보기 캐시의 이름을 파일의 크기·수정 시각·inode로 정합니다. 다시 열 때 양쪽 해시를 생략합니다. | `bridge.py`의 `preview` |
| 올린 새 파일은 계정 기본 권한으로, 덮어쓴 파일은 기존 권한으로 게시합니다. 이전에는 0600이 됐고, 0755 스크립트를 덮어써도 0600이 됐습니다. | `file_host.py`의 `publish_mode` |

## PDF 뷰어

| 변경 | 위치 |
| --- | --- |
| 화면에 없는 페이지를 도우미 한 번에 묶어 렌더링합니다. 문서는 한 번만 엽니다. | `document-view.js`의 `queuePages`, `bridge.py`의 `render_pdf_pages` |
| 화면이 다 채워지면 읽는 방향으로 두 쪽까지 한 쪽씩 미리 읽습니다. | `document-view.js`의 `queuePages` |
| 지나간 페이지 12장의 정보를 기억합니다. 되돌아갈 때 도우미를 띄우지 않습니다. | `document-view.js`의 `trimPages` |
| 글자 위치를 페이지당 변환식 한 번으로 계산하고 소수 다섯 자리로 보냅니다. 회전된 페이지도 테스트에 넣었습니다. | `bridge.py`의 `page_chars` |
| 실패한 페이지는 2초·8초·30초 뒤에만 다시 시도하고 멈춥니다. 이전에는 보이는 두 페이지가 함께 실패하면 끝없이 반복했습니다. | `document-view.js`의 `failPages` |
| 파일이 그대로면 다시 읽지 않고, 오래된 페이지 비트맵만 다시 요청합니다. | `document-view.js`의 `checkForChanges` |
| 로컬 파일의 변경 확인 요청은 무거운 import 전에 답합니다. | `bridge.py`의 `quick_revision` |

## Files 패널

| 변경 | 위치 |
| --- | --- |
| 원격과 리눅스에서는 한 프로그램이 모든 폴더를 나열합니다. 이전에는 펼친 폴더마다 하나씩 띄웠습니다. | `main.js`의 `listFolders` |
| 감시가 알린 변경은 해당 폴더만 2초 간격으로 읽습니다. 보이지 않는 폴더의 변경은 건너뛰고, `.git` 안의 변경은 Git 표시만 갱신합니다. | `main.js`의 `changedFolders`, `noteChanges`, `scheduleChanges` |
| 패널이 숨겨져 있으면 읽지 않고, 다시 보일 때 한 번 읽습니다. | `main.js`의 `shown`, `tick` |
| 전체 읽기 간격은 감시가 동작하면 60초, 원격은 10초이며 목록이 그대로면 30초입니다. 창이 비활성이면 60초입니다. | `main.js`의 `tick` |
| 폴더를 바꾸면 이전 폴더의 감시를 취소합니다. | `main.js`의 `refresh` |

## 보안

| 변경 | 위치 |
| --- | --- |
| 원격 파일 도우미, 사용량 수집기, 링크 확인을 `python -I`로 실행합니다. 작업 폴더(원격에서는 홈)의 파이썬 파일이 표준 모듈 대신 실행되지 않습니다. | `bridge.py`의 `RemoteClient`, `lab-usage/main.js`, `personal-terminal-links/link.js` |
| 저장소 자체 설정에 filter 프로그램이 있으면 `git status`를 실행하지 않습니다. 계정과 시스템 설정의 filter는 그대로 허용합니다. | `main.js`의 `repositoryRunsPrograms` |
| 하위 모듈은 커밋만 비교합니다. 하위 모듈 안에서 그쪽 설정으로 상태를 계산하지 않습니다. | `main.js`의 `refresh` |
| 올리는 임시 파일이 다른 계정의 것이면 쓰지 않습니다. | `file_host.py`의 `open_stage` |
| `folder` 동작은 폴더만 엽니다. | `bridge.py`의 `main` |
| 로컬 Windows 폴더 목록은 System32의 PowerShell을 전체 경로로 부릅니다. 그 경로가 없으면 이름으로 부릅니다. | `main.js`의 `windowsDirectory` |

## 정리

| 변경 | 위치 |
| --- | --- |
| 하루 넘은 `.herdr-upload-`, `.herdr-download-`, `.herdr-copy-` 임시 파일을 지웁니다. | `file_host.py`의 `sweep_stale` |
| 한 시간 넘은 캐시 `.part`와 하루 넘은 `jobs/` 파일을 지웁니다. | `bridge.py`의 `prune_cache`, `sweep_jobs` |
| 설치 백업은 최근 5개와 현재 상태가 가리키는 것만 둡니다. | `kit.py`의 `prune_backups` |
| Files가 폴더별로 기억하는 펼침 상태를 50개로 제한합니다. | `main.js`의 `refresh` |

## 쓰면서 달라지는 점

- 저장소 자체 설정에 filter가 있는 폴더에서는 Git 표시 대신 목록 아래에 안내 줄이 나옵니다. 그 줄을 누르면 저장소가 신뢰 목록에 들어가고 표시가 돌아옵니다. git-lfs를 저장소 단위로 설치한 경우도 해당됩니다.
- 하위 모듈은 커밋이 바뀐 경우에만 표시됩니다.
- 창이 비활성일 때 Files 목록 갱신이 느려집니다.
- 실패한 PDF 페이지는 세 번 재시도한 뒤 멈춥니다. 페이지를 클릭하거나 확대하면 다시 시도합니다.
- 서버에 올린 파일의 권한이 0600에서 계정 기본값으로 바뀝니다.

## 측정

리눅스에서 v1.6.0과 같은 조건으로 쟀습니다. 원격 수치는 SSH 없이 한 서버 안에서 `hc exec`(0.1.22)를 왕복한 값입니다. PDF는 pypdfium2 5.15.2와 조밀한 논문 PDF를 썼습니다.

| 항목 | v1.6.0 | v1.7.0 |
| --- | ---: | ---: |
| 원격 올리기 / 내려받기, 256 MiB | 6.0 / 6.5 MiB/s | 21.6 / 38.4 MiB/s |
| 같은 PC 안 전송 | 78~111 MiB/s | 365~620 MiB/s |
| 세 쪽 렌더링, 비트맵 캐시 있음 | 493ms, 도우미 3회 | 204ms, 도우미 1회 |
| 글자 위치 응답, 6,714자 페이지 | 568 KiB | 283 KiB |
| 변경 확인 도우미 1회 | 57ms | 38ms |
| 12쪽 넘겨 읽을 때 빈 채로 도착한 페이지 | 36번 중 12번 | 0번 |
| 6쪽 되돌아갈 때 도우미 실행 | 6회 | 1회 |

표의 마지막 두 줄은 쪽당 3초씩 읽는다고 가정한 모의 실험입니다.

## 바뀐 파일

| 파일 | 내용 |
| --- | --- |
| `work/personal-files/bridge.py`, `file_host.py` | 전송, PDF 렌더링, 캐시 정리 |
| `work/personal-files/main.js` | Files 새로고침, 작업 창, Git 표시 |
| `work/personal-files/document-view.js` | PDF 페이지 로딩 |
| `work/lab-usage/main.js`, `work/personal-terminal-links/link.js` | `python -I` |
| `work/herdr-mod-kit/kit.py` | 버전, 백업 정리 |
| `work/kit-tools/stage.py`, `handoff.py`, `check-speed.py`, `verify.py`, `check-tabs-and-links.cjs` | 변환 기준과 검사 갱신 |
| `test_bridge.py`, `test_pdf.py`, `test_ui.mjs`, `test_pdf_ui.mjs`, `test_sources.mjs`, `test_install.py` | 새 동작의 테스트 |
