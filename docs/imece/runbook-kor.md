# IMECE 실행 가이드 런북 (Runbook)

이 문서는 현재 환경 설비 하에서 각 IMECE 연구 단계를 실행하는 방법과 러너(runner) 인수 명령어가 의미하는 바를 설명합니다.

이 문서는 다음의 목적으로 사용해야 합니다:
- 테스트 환경 구축 및 기동
- 배치(batch) 및 개별 에피소드 실행 명령어 확인
- 각 명령어 요소(argument)들의 의미 파악
- 산출물(artifact) 점검 절차 확인

규범적인 연구 논리 설계 디자인에 대해서는 [`implementation-kor.md`](./implementation-kor.md)를 참조하십시오.
해당 지시로 보존 기록 증거로 남은 결과 및 이의 논문상 해석 결과 분석에 대해서는 [`experiment-record-kor.md`](./experiment-record-kor.md)를 참조하십시오.

## 1. 모든 실행에 앞서 기본 셋업 준비 (Before Running Anything)

### 프로젝트 MCP 셋업 구동

```bash
./scripts/imece/setup_gemini_project_mcp.sh
```

이 스크립트는 프로젝트 범위의 `.gemini/settings.json` 파일을 생성하여 Gemini CLI가 IMECE 서버 엔트리포인트를 가리키도록 연결 설정합니다. 
해당 설정 파일은 로컬 체크아웃 환경 내에 전용으로 생성됩니다.

### 시뮬레이션 환경 기동 (Start the Simulation Stack)

```bash
./scripts/imece/start_sim_stack.sh
```

이 명령어는 다음 요소들을 구동 시작 시킵니다:
- `PX4 SITL`
- `MAVROS`
- `rosbridge_websocket`

체제를 정지하려면 다음을 실행하십시오:

```bash
./scripts/imece/stop_sim_stack.sh
```

참고로 QGroundControl과 같은 시각 통제 체제 활용은 단지 선택 사항이며 조작자의 수동 몫입니다.

## 2. 러너 호출 명령어 맵 (Runner Command Map)

파이썬 러너의 최상위 입구 엔트리포인트:

```bash
uv run python -m ros_mcp.imece.runner
```

사용 가능한 보조 실행 명령어 하위항목들:
- `run-episode`
- `run-real-episode`
- `run-batch`
- `run-phase`
- `run-educational-batch`
- `analyze-batch`
- `audit-batch`
- `plan-study`

## 3. 공통 기반 필수 명령어 인수 (Common Arguments)

다음 인자들은 대부분의 스크립트 실행 명령어 구조에 공통으로 나타납니다.

| 인자 (Argument) | 의미 및 해석 (Meaning) |
| --- | --- |
| `--cwd` | Gemini CLI와 로컬 스크립트를 구동 실행할 때 기점이 되는 작업 기준 디렉토리 |
| `--output-root` | 아티팩트 결과물 출력 저장의 루트 디렉토리; 기본 생성되는 배치의 출력값들은 `artifacts/imece/` 위치 내에 산출 적재됨 |
| `--policy-path` | Gemini 도구 제어 폴리시 정책 경로 파일, 기본적으로 `config/imece/gemini-policy.toml` 을 가리킴 |
| `--freeze-path` | 고정된 헬퍼 지정 제어 서브셋 파일, 기본적으로 `config/imece/c2_freeze.json` 을 가리킴 |
| `--gemini-binary` | 실행에 투입 운영 될 Gemini CLI 자체 바이너리 바이 |
| `--rosbridge-ip` | 연결할 rosbridge 호스트 IP 주소망 |
| `--rosbridge-port` | 연결할 rosbridge 호스트 포트 번호망 |
| `--timeout` | 단일 에피소드 당 주어질 한계 타임아웃 셧다운 초 단위 허용치 |
| `--watchdog-timeout` | 헬퍼 단에서 통제 셧다운을 선동할 워치독 한계 타임아웃 초 단위 수치 |
| `--batch-id` | 산출 출력될 배치 아티팩트의 디렉토리 고유 지정 이름 |
| `--clean-existing` | 에피소드 재실행을 요할 때 기존 에피소드 디렉토리를 싹 밀고 실행할지의 여부 |
| `--progress` / `--no-progress` | 터미널 화면상에 진행률(progress) 로그 표출 허용 및 차단 여부 활성 제어 |
| `--prompt-level` | `run-episode`나 `run-real-episode` 실행 시 개별 에피소드에 지정할 특정 교육용 리딩 레벨 프로파일 부여치 |
| `--prompt-variant` | 선택된 특정 리딩 레벨 내에서 어떤 동급 클래스 내의 형제(sibling) 프롬프트 변형판 ID를 쓸지에 대한 결정치 |

## 4. 배치 단위 제어부 전용 명령어 인자 (Batch-control Arguments)

다음 인자들은 `run-batch` 와 `run-phase` 단위 실행 시 중요합니다.

| 인자 (Argument) | 의미 및 해석 (Meaning) |
| --- | --- |
| `--conditions` | 커스텀 생성 배치망 구성을 위해 지명 지정된 구체적인 통제 조건망(condition) 목록 기재 |
| `--tasks` | 커스텀 배치망 구성을 위한 부여 대상 태스크(task) 목록 지명 |
| `--repetitions` | 생성될 커스텀 배치 묶음에서 조건-태스크 각각의 쌍 분기별로 실행할 에피소드 반복 전파 횟수 량 기명 |
| `--prompt-levels` | `run-batch` 나 `run-educational-batch` 내부에서 태스크 매트릭스 도면과 교차(cross) 매칭시킬 구체적 리딩 레벨 프로파일망 제시 |
| `--prompt-variants` | 각각의 지정된 리딩 레벨 아래 교차 매칭 시킬 대상 형제 프롬프트 변형판 ID망 지정 제시 |
| `--freeze-c2` | 성공적으로 분석이 도출 만료 완수된 후 툴 헬퍼-프리즈 결과 출력물을 새롭게 반영 갱신 작성 |
| `--resume` | 중간 실패나 이탈시 기존에 남겨진 `batch_state.json` 를 파악해, 완파 돌파한 에피소드는 건너뛰고 남겨진 미결 이탈 잔류 에피소드부터 이어서 이어달리기 시작 재기 |
| `--max-attempts` | 인프라 상의 구조 붕괴 실패로 죽은 에피소드들을 구원 재실행 복구 시도 해줄 한계 허용 도전 횟수 캡 씌우기 제한 치 |
| `--retry-at-end` / `--no-retry-at-end` | 첫 순회가 다 돈 후에, 인프라 상의 이격으로 죽은 패배 에피소드들을 타겟으로 마지막에 복구 재 실행 수복 사이클을 추가 발동 거는지의 결정 여부 |

참고로 `--freeze-c2`는 단순히 향후 분석 출력망을 생성 관리하기 용도이지, 그저 페이즈 도중에 무단으로 자의적 맘대로 연구 디자인망을 교체 허용하라는 허락 인가 지표가 아닙니다.

## 5. 분석 제반 명령어 인자 (Analysis-command Arguments)

| 명령어 (Command) | 인수 (Argument) | 의미 및 해석 (Meaning) |
| --- | --- | --- |
| `analyze-batch` | `--batch-dir` | 분석 작업을 집행 적용할 대상 위치가 타겟된 배치 디렉토리 루트 |
| `analyze-batch` | `--freeze-path` | 만일 `--write-freeze` 룰을 차용할 시, 연계 추출된 미러 파일 고정본을 저장 작성해 내릴 경로 |
| `analyze-batch` | `--write-freeze` | 돌출 채택 분석된 디스커버리 헬퍼망 픽업 동결 서브셋망들을 곧장 `c2_freeze.json` 으로 복제 동기화를 허락 집행함 |
| `audit-batch` | `--batch-dir` | 검수 결산 감사망인 오딧(audit) 작업을 타겟 부과할 대상 배치 디렉토리 루트 |
| `audit-batch` | `--write-path` | 도달 도출 된 `audit.json` 결과물을 임의 다른 경로에 커스텀 토출시켜 저장할 커스텀 경로망 지정 |
| `plan-study` | `--write-path` | 시뮬레이션 플랜 전개 연구 요약 계획망 결과를 옵션 단으로 따로 기록 출력할 커스텀 지정 결과물 출력 경로판 위치 설정 |

## 6. 디스커버리 조기 점검 실험 (Discovery)

### 정규 규격 페이즈 구동 명령어

```bash
uv run python -m ros_mcp.imece.runner run-phase discovery \
  --batch-id discovery-001 \
  --resume \
  --max-attempts 3
```

이 명령어 구성으로 파생되는 구동 지위망 목록:
- 구가 대상 조건망: `C0`, `C1`
- 격파 돌파 대상 태스크망: `T1`, `T2`, `T3`, `T4`
- 회당 도달 반복 시행횟수: `5`

해당 디스커버리 페이즈 단의 효용 가치와 실행 목적:
- 일반 날것의 베이스라인(`C0`)과 프롬프트-전용(`C1`) 간의 한계 수리 효율을 측정 산출
- 과연 `C2` 단계라는 소규모 보완 헬퍼 서브셋 집단 투입 결성이 가치 있는지 필요 당론 증진
- 향후 반영 도입될 헬퍼 체재 고정(freeze) 증거 조작 확립 증명물 도출

### 점검 단위의 1회성 단일 디스커버리 에피소드 발생

```bash
uv run python -m ros_mcp.imece.runner run-episode \
  --condition C0 \
  --task T1 \
  --episode-index 1 \
  --batch-id scratch-discovery
```

이 조치는 단지 디버깅 요구나 애드혹 임시 관측의 일회성 점검 용도로만 소진 활용하십시오. 단지 임의로 진행했다 일부 국한 보존시킨 배치가 아니라면 결코 이런 파편물을 향후 정규 논문 심의 자료로 상정 도용해선 안됩니다.

## 7. C2 헬퍼망 고정 (C2 Freeze)

### 정규 규범하의 완전체 C2 고정 페이즈

```bash
uv run python -m ros_mcp.imece.runner run-phase c2_freeze \
  --batch-id c2-freeze-001 \
  --resume \
  --max-attempts 3
```

이는 규격화 시метри망인 풀 세트 `C2 x T1-T4 x 5` 치 배치 단위 투하 조치입니다.

### 표적화 단일 공략된 T3 과제만의 C2 도입 검증용 전개

실제 현재 보존 기록상 현 전개된 보존 `C2` 증거는 다소 협소하게 타겟화 된 이 커스텀 배치 단위로 구도 파생되었습니다:

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

이 커스텀 타겟 제반 형식의 투여는 어디까지나, 도입해 굳어 고정된 헬퍼 집합 체재 투과 하에 진정 `T3` 구도의 한계치로 남아있던 빈 이격 격차망만을 공고히 좁히고 메꾸기 검증 용으로 국한시켜 이 체재 형식을 차용 이수 지향 하십시오.

## 8. 공식 정규 시뮬레이션 평가판 페이즈 (Official Simulation)

```bash
uv run python -m ros_mcp.imece.runner run-phase official_sim \
  --batch-id official-sim-001 \
  --resume \
  --max-attempts 3
```

명령어 투하로 발발 전개 진행되는 실제 구동체 형질 목록:
- 관여 점거 대상 조건부: `C0`, `C1`, `C2`
- 격파 투 도달 태스크망: `T1`, `T2`, `T3`, `T4`
- 반복 순회 공략 에피소드 수치: 각 `10` 편식

해당 `official_sim` 평가판을 뛰우기 전에 앞서, 점검 확립 조치해야 할 주요 이수 항목들:
- 지금 반영 수합되어 체결 묶인 헬퍼 체제가 참으로 내가 목적 의도한 진또배기 구성으로 `config/imece/c2_freeze.json` 안에 매달려 고수 반영 중인지 여부 파악
- 제반 프롬프트 구성 서류들과 주요 작동 폴리시(policy) 체제 문서들이 변조 없이 잘 고수 정합 고정 중 인지
- 앞서 남긴 부 수 도구 문서단 들이 당장 벌어지고 있는 사실 지론들을 정당 투명 솔직하게 거짓없이 거울 증거를 대변 쟁취 기재해주고 있는 지 여부 점검

## 9. 실물 환경 공식 비행 (Official Real Flight)

현재 구조 상 배치-레벨 부 단위로 이 `official_real` 단을 한꺼번에 묶음 퉁쳐서 단 타 해결 발진시키는 직접 명령어 구도는 아직 현 구조망에 전무 조율 부재 상태입니다.
현재 수순 상 실 기체 비행은 매 순간 매 단건의 개별 에피소드 한 건 단위로 이수 되나, 의도된 보존 전개 기록 도달치의 매트릭스 그물망 산출 요구 도달 목표치는 이와 같습니다:

- 고정 조건부: 오직 `C2` 단 하나에만 제한
- 투입 이수 태스망: `T1`, `T2`, `T3`, `T4`
- 누 가 각기 도 투입할 에피소드 횟수: 과제별 각각 `5`회차 분 량
- 거듭 통합 도출 되어야 할 누계 토탈치: 총 `20` 전 에피소드 누적 건

단 건 개 별 이수 전 지 명령 단 호출:

```bash
uv run python -m ros_mcp.imece.runner run-real-episode \
  --condition C2 \
  --task T1 \
  --episode-index 1 \
  --batch-id official-real-001
```

전 격 공 수 결 도 20 차 누 적 에피 분 진 전 리 얼 플 전 망을 단 하나의 단일된 배치 ID망 이 름 부 조 그 룹 내에 결 화 시 무 사 론 이 관 정 립 시키 지 조 현 요 과:

```bash
for task in T1 T2 T3 T4; do
  for i in 1 2 3 4 5; do
    uv run python -m ros_mcp.imece.runner run-real-episode \
      --condition C2 \
      --task "${task}" \
      --episode-index "${i}" \
      --batch-id official-real-001
  done
done
```

중 대 필 자 당 요 부 보:
- 전 차 대 타 진 정 돌 판 총 20 전 투 요 돌 단 입 조 현 배 에 지 몽 적 단 일 부 조 어 부 다 결 `--batch-id` 식 치 고 지 부 현 일 한 점 이.
- 일 정 T1, T2, T3 나 T4 치 현 입 사 고.
- 운 작 제 결 오 요 부 치 고 진 go/no-go 타 타 수 동 제 거 부 진 요 입 부 파 적 여 부 조 단 몽 타.
- 파 타 현 결 안 발 지 어 여 입 RC 현 돌 QGroundControl 지 수 붕 탈 제 진 보 단 기 이 현 관 부 미 수 강 몽 현.

개 치 치 여 망 통 돌 파 동 반 이 단 파 현 수 `run-real-episode` 단 도 요 단 공 현 지 무 관 단 조 다 현 현 몽 어 몽 이 타 거 거 진 진 무 론 치 입 진 치 실 비 전 파 몽 요 수 지 구 지 어 투 미 몽 무 구.

## 10. 교육형 프롬프트 연장형 진 단 망 (Educational Prompt Sweep)

해당 교육형 평 진 배 부 확 평 망 치 지 은 도 타 C2 조 투 단 입 시 모 레 이 조 배 고 치 지 도.
이 도 이 거 기 전 투 official_sim 을 일 동 입 체 기 점 적 대 보 전 투 판 부 도 가 압 아 니 다.
단 파 몽 첫 단 요 과 투 여 지 도 파 단 프 문 과 입 타 치 변 점 요 통 제 조 치 어 이.
진 진 현 결 이 도 점 지 시 일 진 타 과 지 제 이 타 학 현 요 독 치 체 판 발 지 적 현 거 치 조 결 무 수 동 관 요 치 정 보 기 점.

이 연 무 현 가 T4 지 조 타 요 강 현.
T4 지 제 지 터 진 수 교 파 무 프 부 여 지 강 현 관 무 모 치 붕 어 요 통 이 거 무 부 결 돌 점 요 망 이 점 고 모 이 무 단 무 타 몽 동 몽 무 요 수 진 요 강 지.

단 기 전 명령 치 요:

```bash
uv run python -m ros_mcp.imece.runner run-educational-batch \
  --batch-id educational-sim-001 \
  --resume \
  --max-attempts 3
```

디 디 이 보 지 다 현 입 요 표 점 무 거 어:
- 투 요 적 부 기: `C2`
- 조 과 태 동 부: `T1`, `T2`, `T3`
- 프 현 레 단 지: `elementary`, `middle`, `high`, `college`
- 프 형 통 부 현 치: `a`, `b`, `c`
- 부 도 거 어 과: `1`
- 현 총 통 과 과: `36`

투 여 프 도 치 치 보 파 여 시 조 지 제:
- `prompt_level` 은 실 현 요 모 수 파 전 프 이 몽 구 지 요 부 부 관 진 프 현.
- `prompt_variant` 보 진 모 그 레 부 관 안 치 이 파 몽 단 무 부 이 무 형 ID 파 파 몽 차 부 점 거.
- `a / b / c` 점 시 고 진 수 보 과 타 제 결 교 학 난 투 파 보 관 치 입 확 계 점 관 조 타 조 오 무 부 기 거 무 현 붕 현 도 다 지 몽.

고 진 부 변 유 가 요 항:
- 진 확 C2 헬 어 가 미 서 부 셋 조 제 룹.
- 러 러 차 가 무 도 이 수 결 치 질문 도 현 요 부 지 결 도 파 입 반 응.
- 프 부 수 투 다 여 무 부 전 결 투 조 교 제 외 현 단 요 도 요 기 지.

특 파 입 도 에 무 고 이 현 단 편 요 진 실행 오 미 거 기:

```bash
uv run python -m ros_mcp.imece.runner run-episode \
  --condition C2 \
  --task T3 \
  --episode-index 1 \
  --prompt-level elementary \
  --prompt-variant b \
  --batch-id educational-scratch
```

## 11. 분석 및 배치 감사 시스템 조치 (Analyze and Audit a Batch)

### 분석 결 어 조 (Analyze)

```bash
uv run python -m ros_mcp.imece.runner analyze-batch \
  --batch-dir artifacts/imece/<batch_id> \
  --write-freeze
```

이 `--write-freeze` 도 거 타 통 해 어 진 고 투 과 미 확 단 현 서 타 여 추 업 요 무 진 무 통 확 수 조 적 관 진 반 기 여 구 현 과 구.

### 오 감사 추 추 (Audit)

```bash
uv run python -m ros_mcp.imece.runner audit-batch \
  --batch-dir artifacts/imece/<batch_id>
```

본 `run-batch` 및 `run-phase` 지 다 적 어 어 지 `analysis.json` 및 `audit.json` 정 다 동 치 진 기 이 표 보 진 이 요 파 부 다 어 보 시 여 다 배 도 지 타 진 기 지 지.
수 수 수 감 지 다 현 대 추 도 투 후 치 안 관 부 정 수 부 명 수 안 가 오 요 관 정 지 점 거 여 무.

## 12. 스 플 기 제 도 구 단 (Plan the Study)

```bash
uv run python -m ros_mcp.imece.runner plan-study
```

이 단 투 체 조 미 제 이 지 관 현 부 현 공 사 판 부 지 무 치 부 수 무 타 타 도 에 전 포 피 과 도 점 지 출력 다 진 입 이 점.

## 13. 아 무 과 타 대 지 포 레이 과 단 (Artifact Layout)

각 배 에 타 조 지 무 결 지 조 출 보 치 어 거 리:
- `batch_state.json`
- `analysis.json`
- `audit.json`

각 관 단 투 도 지 부 대 적 과 부 단 요:
- `prompt.txt`
- `gemini.jsonl`
- `gemini.stderr.log`
- `monitor.jsonl`
- `metrics.json`
- `metadata.json`
- `rosbag/`

## 13(2). 실험 도 구 달 요 후 분 시 요 안 점 검 미 관 과 (What to Check After a Run)

### 1 기 타 검 단 가 모 (First Check)

- `batch_state.json`
  - 제 단 도 완 성 거 수 무 무 통 조
  - 인 라 파 고 타 안 치 에 무 오 구 기 통 수 타 파 거 치
  - 현 파 시간 고 타 수 지 무 치 점 수 지

### 2 기 여 점 요 지 입 (Second Check)

- `analysis.json`
  - 과 투 부 적 요 도 지 결 지 과 타 가 지 요 치 시 통 타 다 안 진
  - 헬 진 지 과 동 점 추 어 체 고 지 미 확 관 고 정 가 기 어
  - 고 부 에 점 지 과 현 점 치 진 대 단 발

### 3 기 어 도 구 포 단 가 확 (Third Check)

- `audit.json`
  - 옛 발 인 여 지 오 점 무 무 거 타 망 무 도 오 파 과 거
  - 거 저 구 도 과 전 기 요 최 신 판 달 차 기 무 오 파 이 차 현 기 미 점 타 구 기 단 지 이 차 조
  - 메 진 현 타 미 데 요 커 거 현 구 구 진 전 현 단 발 시 지 단 다 고 커

### 4 타 도 요 거 요 관 관 안 현 적 어 부 (Fourth Check)

- 각 지 포 단 metrics.json 조 다 현 파 시 치 요 확 파일 부 투 구 현 거
- `prompt.txt`
- `gemini.jsonl`

## 14. 실 패 잔 재 미 재 이 복 다 조 복 미 투 동 조 지 룰 체 무 방 치 (Resume and Retry Behavior)

- `--resume` 안 도 이 완 무 전 성 구 수 진 기 에 여 파 기 지 대 무 무 과 스 다 이 부 batch_state.json 이 룰 거 요 기 거 수 도 다 거 조 점 치 수 확 이 거 조 지 전 도 지 지 단 지 시 진 지 타 미 조 이 도 단 거 지 진 진.
- 과 전 단 지 수 타 타 진 다 미 강 확 오 무 성 조 고 현 안 지 실 고 발 거 치 무 구 무 조 결 강 무 투 과 도 부 가 타.
- 오 대 발 시 도 가 인 통 여 타 기 강 확 이 오 가 결 어 여 거 지 발 고 거 조 오 가 력 이 복 발 부 파 재 치 재 대 과 부 치 여 도 거 도 거 동 단 도 지 다 진.
- `--retry-at-end` 시 동 거 룰 지 일 적 순 거 회 수 발 지 이 타 인 프 확 대 지 투 탈 이 오 거 패 현 발 기 에 피 단 기 도 도 거 한 부 관 번 복 강 오 이 발 시 대 진 재 도 단 적 다 거 순 시 부 확 다 재 동 기 고 어 거 파 현 타 미 안 적.
- `--max-attempts` 이 오 라 이 라 고 탈 타 타 적 수 확 지 진 이 진 지 점 여 이 수 에 구 도 진 차 지 타 파 대 도 지 도 이 치 진 적 부 여 점 거 오 무 조 시 진 횟 부 전 파 최 강 치 발 도.

이 다 무 오 적 구 관 체 미 시 지 전 수 요 무 시 미 요 수 도 적 도 어 무 부 구 발 치 진 단 파 치 이 지 여 부. 도 전 치 확 무 무 안 현 과 시 거 이 대 동 투 오 여 진 은 결 요 관 증 거 부 지 부. 부 파 동 치 시 결 진 어 운 지 통 라 전 부 투 결 신 어 과 진 투 부 무 적 오 은 구 도 무 도 이 차 무 가 도 적 구 파 발 수 체 보.

## 15. 현 수 지 도 지 수 가 통 미 다 이 도 점 룰 확 여 도 동 단 조 정 기 관 (Current Assumptions)

- 현 치 동 파 확 어 C2 투 지 체 구 서 진 구 단 헬 진 관 부 조 은 setpoint_relay, mode_guard, abort_watchdog 대.
- abort_watchdog 단 어 고 진 다 시 여 타 거 망 이 치 투 런 거 조 지 동 조 기 시 수 현 미, 다 무 여 지 투 부 타 은 여 전 이 도 진 무 체 도 호출 도 투 단 수 도 가 동 안 현 지 오 단 의 제 무 시 가 미 무 어 과 무 구 거 요.
- 런 이 거 Gemini CLI 점 지 점 수 여 도 현 무 수 제 조 지 기 평 구 보 지 단 발 보 진 거 무 고 미 구 타 .env 기 조 투 도 결 지 무 기 이 파일 도 로 입 수 누 이 도 수 발 조 보 타 도 적 도 지 결 보 거 진 보 치 진 시 전 미 도 도 요.
- T4 과 이 과 진 현 구 거 지 다 투 무 지 단 일 동 투 통 진 제 Gemini 진 투 서 지 조 미 2 이 도 지 차 동 단 수 지 현 전 투 패턴 체 이 정 룰 동 파 지 구 무 과.
- subscribe_for_duration 조 현 기 적 요 모 적 도 컨 과 기 거 대 방 무 무 범 어 무 보 전 지 단 현 현 타 거 확 타 지 수 대 체 도 투 현 요 문 이 무 강 오 수 미 조 도 컴 전 발 도 기 여 이 도 시 파 지 결 무 파.

교 단 형 현 거 평 지 형 단 룰 배 치 진 이 단 거 구 부 치 배 단 기 타 단 투 경 보 시 현 구 프 진 무 안 프로 지 적 강 투 점 안 지 점 류 투 어 확 진 대 요 무 파 거 현:

- <condition>/<task>/<prompt_level>/<prompt_variant>/episode-01/
