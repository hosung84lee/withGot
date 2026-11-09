# PC로 옮겨 실행하기

## 1. 압축 풀기
ZIP 전체를 Documents 등 원하는 폴더에 압축 해제합니다.
폴더 예: C:\Users\사용자\Documents\insurance-workbench
ZIP 내부에서 파일을 바로 실행하지 마세요.

## 2. 화면만 먼저 보기
Python 3이 있으면 `scripts/preview.cmd`를 실행합니다(Windows).
macOS/Linux에서는 프로젝트 폴더에서 `python3 scripts/preview.py`를 실행합니다.
브라우저: http://127.0.0.1:5173
번들된 화면을 제공하므로 npm/uv 설치 없이 볼 수 있습니다. 소스 수정은 반영되지 않습니다. 개인정보 보호 분석의 서버 조회까지 시연하려면 4절의 웹 개발 서버와 API를 함께 실행하세요.
포트가 사용 중이면 기존 서버를 종료한 뒤 다시 실행합니다.
Google Fonts는 온라인일 때 로드되며 오프라인에서는 기본 글꼴을 사용합니다.

## 3. 개발환경 설치
공식 다운로드:
- Node.js 24 LTS: https://nodejs.org/en/download
- Python 3.12: https://www.python.org/downloads/
- uv: https://docs.astral.sh/uv/getting-started/installation/
- Git(선택): https://git-scm.com/downloads
- VS Code(선택): https://code.visualstudio.com/download

설치 후 새 터미널을 열고 프로젝트 폴더에서:
```
uv sync --locked
npm --prefix apps/web ci
```
Windows에서는 `scripts/setup.cmd`로 위 두 명령을 실행할 수 있습니다.
첫 설치에는 인터넷이 필요하며 Python과 Node.js는 설치하지 않고 사용하는 프로그램입니다.

## 4. 개발 실행
Windows: `scripts/start-ui.cmd` 실행. API는 별도 창에서 `scripts/start-api.cmd` 실행.
macOS/Linux: `bash scripts/dev.sh`
웹: http://127.0.0.1:5173 / API: http://127.0.0.1:8000/docs
화면 초안은 API·OCR·LLM 키 없이도 동작합니다.

## 5. 검증
```
uv run ruff check apps/api
uv run pytest
npm --prefix apps/web run build
```
Windows 스크립트는 이 Linux 환경에서 실행 검증하지 못했습니다.
클라우드에서는 같은 명령의 Python 검사·API 테스트·웹 빌드를 확인했습니다.

## 6. ChatGPT 데스크톱에서 이어가기
Codex에서 압축을 푼 insurance-workbench 폴더를 열고 다음처럼 요청합니다:
“이 폴더의 LOCAL_SETUP.md와 docs/DEVELOPMENT.md를 읽고 개발을 이어가줘.”
PC 페어링 자체가 파일 복사나 폴더 열기를 자동 수행하지는 않습니다.

## 포함·제외
포함: React 소스, FastAPI·MCP 골격, 빌드 화면, lock 파일, 개발 문서, 웹 자료 출처 목록.
제외: .venv, node_modules, Git 이력, API 키, 실제 의료서류, 수집 PDF 원본.
공개 PDF는 data/reference/sources.json의 URL에서 다시 받을 수 있습니다.
지원 서식의 텍스트 PDF 기기 내 추출과 전송 검토, 가상 보장 후보 조회를 지원합니다. 스캔·사진 OCR과 실제 약관 판정·보험금 계산은 후속 구현 대상입니다.
