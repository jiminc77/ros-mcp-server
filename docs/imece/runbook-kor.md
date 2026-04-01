# IMECE 런북 (Runbook)

이 문서는 현재 머신에서 각 IMECE 연구 단계를 실행하는 방법과 러너(runner) 인수들의 의미를 설명합니다.

다음의 경우에 이 파일을 사용하세요:

- 환경 구축 (Environment bring-up)
- 배치(batch) 및 에피소드 실행 명령어
- 인수(argument) 의미
- 산출물 검사 워크플로우

규범적인 연구 설계에 대해서는 [`implementation-kor.md`](./implementation-kor.md)를 참고하세요.
보존된 결과 및 해석에 대해서는 [`experiment-record-kor.md`](./experiment-record-kor.md)를 참고하세요.

## 1. 실행 전 준비 사항

### 프로젝트 MCP 설정

```bash
./scripts/imece/setup_gemini_project_mcp.sh
```

이 명령어는 Gemini CLI가 IMECE 서버 진입점을 가리키도록 하는 프로젝트 범위의 `.gemini/settings.json`을 작성합니다.
해당 파일은 체크아웃된 리포지토리 로컬 환경에 존재합니다.

### 시뮬레이션 스택 시작하기

```bash
./scripts/imece/start_sim_stack.sh
```

다음 항목들을 시작합니다:

- `PX4 SITL`
- `MAVROS`
- `rosbridge_websocket`

중지하려면 다음을 실행하세요:

```bash
./scripts/imece/stop_sim_stack.sh
```

QGroundControl(QGC) 실행은 선택 및 수동 사항입니다.

## 2. 러너 명령어 맵

러너 시작 지점은 다음과 같습니다:

```bash
uv run python -m ros_mcp.imece.runner
```

사용 가능한 하위 명령어:

- `run-episode`
- `run-real-episode`
- `run-batch`
- `run-phase`
- `analyze-batch`
- `audit-batch`
- `plan-study`

## 3. 공통 인수 (Common Arguments)

다음은 대부분의 실행 명령에서 나타나는 인수입니다.

| 인수 | 의미 |
| --- | --- |
| `--cwd` | Gemini CLI 및 로컬 스크립트를 시작할 때 사용되는 작업 디렉토리 |
| `--output-root` | 산출물 루트 디렉토리; 기본적으로 배치 출력물은 `artifacts/imece/` 아래에 저장됨 |
| `--policy-path` | Gemini 툴 정책 파일, 보통 `config/imece/gemini-policy.toml`에 위치함 |
| `--freeze-path` | 고정된 헬퍼 서브셋 파일, 보통 `config/imece/c2_freeze.json`에 위치함 |
| `--gemini-binary` | 실행할 Gemini CLI 바이너리 |
| `--rosbridge-ip` | rosbridge 호스트 IP |
| `--rosbridge-port` | rosbridge 포트 |
| `--timeout` | 초(seconds) 단위의 에피소드 하드 타임아웃 제한 |
| `--watchdog-timeout` | 초 단위의 헬퍼 측 중단 워치독 타임아웃 제한 |
| `--batch-id` | 출력될 배치 디렉토리명 |
| `--clean-existing` | 에피소드를 다시 실행하기 전에 기존 에피소드 디렉토리를 제거함 |
| `--progress` / `--no-progress` | 터미널 진행률 로그(progress logs) 출력 활성화 또는 비활성화 |

## 4. 배치 제어 인수 (Batch-control Arguments)

`run-batch` 및 `run-phase` 명령어 시 중요한 인수입니다.

| 인수 | 의미 |
| --- | --- |
| `--conditions` | 커스텀 배치를 위한 명시적 조건 리스트 |
| `--tasks` | 커스텀 배치를 위한 명시적 태스크 리스트 |
| `--repetitions` | 커스텀 배치의 조건-태스크 쌍별 반복 횟수 |
| `--freeze-c2` | 성공적인 분석 완료 후 업데이트된 헬퍼 고정 출력 파일 저장 |
| `--resume` | `batch_state.json`부터 이어가며 완료된 에피소드는 건너뜀 |
| `--max-attempts` | 인프라 오류 발생 시 에피소드의 재시도 최대 횟수 지정 |
| `--retry-at-end` / `--no-retry-at-end` | 첫 번째 단계가 끝난 후 인프라 오류가 발생한 에피소드에 대해 두 번째 단계의 단일 재시도 수행 |

`--freeze-c2`는 분석 출력을 관리하기 위함입니다. 연구 설계의 페이즈 중간에 변경을 허가하는 것이 아닙니다.

## 5. 분석 명령 인수 (Analysis-command Arguments)

| 명령어 | 인수 | 의미 |
| --- | --- | --- |
| `analyze-batch` | `--batch-dir` | 분석할 대상 배치 디렉토리 |
| `analyze-batch` | `--freeze-path` | `--write-freeze`를 사용할 때 헬퍼 고정 파일(freeze mirror)을 저장할 경로 |
| `analyze-batch` | `--write-freeze` | 검색된 헬퍼 선택 내역을 `c2_freeze.json`으로 동기화(sync)하여 저장 |
| `audit-batch` | `--batch-dir` | 감사(audit) 대상 배치 디렉토리 |
| `audit-batch` | `--write-path` | 사용자 지정 `audit.json` 출력 파일 경로 |
| `plan-study` | `--write-path` | 연구 계획 요약을 출력할 파일 (선택) |

## 6. 발견 페이즈 (Discovery)

### 표준 페이즈 명령어

```bash
uv run python -m ros_mcp.imece.runner run-phase discovery \
  --batch-id discovery-001 \
  --resume \
  --max-attempts 3
```

실행 조건 구성:

- 조건: `C0`, `C1`
- 태스크: `T1`, `T2`, `T3`, `T4`
- 반복 횟수: `5`

발견 내용 활용처:

- 오리지널 베이스라인과 프롬프트-전용 기반 복구를 측정합니다.
- `C2` 단계 진입이 정당한지 의사 결정을 수행합니다.
- 헬퍼 모듈 고정(freeze) 필요성에 대한 증거를 생성합니다.

### 1회성 발견 에피소드(단일 에피소드 실행)

```bash
uv run python -m ros_mcp.imece.runner run-episode \
  --condition C0 \
  --task T1 \
  --episode-index 1 \
  --batch-id scratch-discovery
```

이 명령어는 디버깅 및 단일 점검 용도로만 사용하세요. 의도적으로 보존하는 배치가 아닌 이상 논문 증거 용도로 사용할 수 없습니다.

## 7. C2 고정 (C2 Freeze)

### 표준 전체 C2 고정 페이즈

```bash
uv run python -m ros_mcp.imece.runner run-phase c2_freeze \
  --batch-id c2-freeze-001 \
  --resume \
  --max-attempts 3
```

이 명령어 수행의 형태는 정확히 `C2 x T1-T4 x 5` 배치 구성과 일치해야 합니다.

### T3를 위한 타겟팅된 C2 검증

현재 보존된 `C2` 증거는 더욱 좁은 범위를 가지며, 다음과 같은 사용자 지정 배치를 사용합니다:

```bash
uv run python -m ros_mcp.imece.runner run-batch \
  --conditions C2 \
  --tasks T3 \
  --repetitions 5 \
  --batch-id c2-freeze-t3-001 \
  --resume \
  --retry-at-end \
  --max-attempts 3
```

이 방식은 이미 고정된 서브셋 하에서 남은 `T3` 격차의 검증이 필요한 특수한 경우에만 사용되어야 합니다.

## 8. 공식 시뮬레이션 (Official Simulation)

```bash
uv run python -m ros_mcp.imece.runner run-phase official_sim \
  --batch-id official-sim-001 \
  --resume \
  --max-attempts 3
```

실행 조건 구성:

- 조건: `C0`, `C1`, `C2`
- 태스크: `T1`, `T2`, `T3`, `T4`
- 반복 횟수: `10`

`official_sim`을 실행하기 전 확인해야 할 사항:

- 헬퍼 모듈의 고정된 서브셋 내용이 `config/imece/c2_freeze.json`의 내용과 의도적으로 일치하는지 확인합니다.
- 프롬프트 파일과 정책 파일이 고정되었는지 확인합니다.
- 문서에 현재 존재하는 기록(증거)들을 솔직하게 표현하고 있는지 다시 한번 검토합니다.

## 9. 공식 실제 비행 (Official Real Flight)

배치(batch) 레벨의 `official_real` 페이즈 명령어는 아직 존재하지 않습니다.
현재 실제 비행 실행은 한 번에 한 개의 에피소드를 처리합니다:

```bash
uv run python -m ros_mcp.imece.runner run-real-episode \
  --condition C2 \
  --task R1 \
  --episode-index 1 \
  --batch-id official-real-r1-001
```

중요 사항:

- 시뮬레이션 게이트를 통과한 후 적용할 때는 `C2`를 프로모션(승급)된 올바른 조건으로 변경하세요.
- `R1` 또는 `R2`를 사용하세요.
- 운영자(operator)가 Go/No-go 관련 판단을 지속적으로 수동으로 체크해야 합니다.
- 만약을 위한 조종기(RC) 및 QGroundControl에서의 권한 탈취(takeover) 준비가 되어 있어야 합니다.

의도적으로 한 개의 논리적인 실제 비행 배치로 구성하여 기록을 보존하지 않는 한, 단순하게 반복 실행된 여러 번의 수동 `run-real-episode` 결과들을 모두 공식 실제 비행 배치로 취급하지 마세요.

## 10. 배치 분석 및 감사 (Analyze and Audit a Batch)

### 분석 (Analyze)

```bash
uv run python -m ros_mcp.imece.runner analyze-batch \
  --batch-dir artifacts/imece/<batch_id> \
  --write-freeze
```

배치로 인해 고정된 헬퍼의 하위 세트를 정의하거나 갱신하려는 경우에만 `--write-freeze` 인수를 사용하세요.

### 감사 (Audit)

```bash
uv run python -m ros_mcp.imece.runner audit-batch \
  --batch-dir artifacts/imece/<batch_id>
```

`run-batch`와 `run-phase`는 배치가 완료된 후 자동으로 `analysis.json` 및 `audit.json`을 작성하도록 되어 있습니다.
명령어를 통한 수동 재분석은 작업 이력을 수정(사후 검사)하거나 명시적인 재검사가 필요한 경우에 사용합니다.

## 11. 연구 설계 문서화 (Plan the Study)

```bash
uv run python -m ros_mcp.imece.runner plan-study
```

이 명령어는 현재 정의된 사양에 따라 포함될 수 있는 공식 에피소드의 수를 터미널에 프린트합니다.

## 12. 산출물 레이아웃 (Artifact Layout)

각 배치가 생성하는 파일:

- `batch_state.json`
- `analysis.json`
- `audit.json`

각 에피소드가 생성하는 파일:

- `prompt.txt`
- `gemini.jsonl`
- `gemini.stderr.log`
- `monitor.jsonl`
- `metrics.json`
- `metadata.json`
- `rosbag/`

## 13. 실행 완료 후 검토 사항 (What to Check After a Run)

### 첫 번째 단계

- `batch_state.json`
  - 에피소드 완료 횟수
  - 인프라 에러 횟수
  - 타임아웃 등으로 소진된(exhausted) 에피소드 횟수

### 두 번째 단계

- `analysis.json`
  - 태스크 성공 요약
  - 헬퍼 고정(freeze) 리뷰 결과
  - 실패 횟수(failure counts)

### 세 번째 단계

- `audit.json`
  - 기록된 과거 인터페이스 불일치(mismatch) 발생 건수
  - 구 채점 방식과 현재 채점 방식 간의 태스크 성공 비율 편차(drift) 값
  - 런타임 메타데이터 커버리지

### 네 번째 단계

- 배치 중 대표적인 `metrics.json` 파일들
- `prompt.txt`
- `gemini.jsonl`

## 14. 재개(Resume) 와 재시도(Retry) 의 동작 원리

- `--resume` 인수는 성공적으로 완료된 에피소드들을 건너뛰고 오직 `batch_state.json`에서 완료되지 않은 작업에 대해 재개합니다.
- 태스크 실패(task failures) 결과는 여전히 타당한 실패로 남습니다.
- 반드시 인프라 오류가 발생한 경우에 한정하여 재시도를 진행해야 합니다.
- `--retry-at-end` 매개변수는 인프라가 원인이 되어 오류를 발생시킨 에피소드들에 대해 두 번째 주기의 전체 반복 점검을 수행합니다.
- `--max-attempts`는 인프라 오류 조건 에피소드의 최대 횟수를 제한합니다.

이러한 분리는 매우 중요한 부분입니다. 제어 과정에서 발생된 실패(Control failures)는 현 상태의 중요한 증거가 됩니다. 그러나 연결 커넥터나 실행-전송 상의 실패는 재시도의 요건을 충족합니다.

## 15. 현재의 가정들 (Current Assumptions)

- 보존을 위한 `C2` 고정 헬퍼 서브셋은 `setpoint_relay`, `mode_guard`, `abort_watchdog`으로 설정되어 있습니다.
- `abort_watchdog`은 단순한 실행 관찰 및 판단을 위해 실행되는 기능입니다. 에이전트가 호출 가능한 언어학 기반 시맨틱 도구(semantic tool)가 아닙니다.
- 러너(Runner)는 Gemini CLI를 시작하기 전에 구성요소 누락 변수를 리포지토리의 로컬 `.env` 파일에서 읽어와 적용합니다.
- `T4`는 단일 개의 Gemini 세션에서 두 개의 턴(two-turn) 패턴으로 구성되어 실행됩니다.
- `subscribe_for_duration`은 모델의 컨텍스트 데이터를 장황하게 유지하는 대신 요약된(압축된) 정보를 반환합니다.
