# IMECE 연구 사양 및 구현 맵 (Study Specification and Implementation Map)

이 문서는 IMECE 단계적 경계 연구(staged boundary study)에 대한 규범적인(normative) 단일 진실 공급원입니다.

다음의 경우에 이 파일을 사용하세요:

- 논문의 의도된 논증 흐름 확인
- 고정된 실험 경계 및 성공 기준 확인
- 리포지토리의 현재 구현 맵 확인
- 각 연구 페이즈(phase)의 정확한 의미 확인

실제로 실행된 내역에 대한 보존된 증거와 논문용 결과 해석에 대해서는 [`experiment-record-kor.md`](./experiment-record-kor.md)를 사용하세요.
명령어 및 운영자 단계에 대해서는 [`runbook-kor.md`](./runbook-kor.md)를 사용하세요.
향후 에이전트가 결과를 분석하고 문서 세트를 업데이트하는 방법에 대해서는 [`agent-development-guide-kor.md`](./agent-development-guide-kor.md)를 사용하세요.

## 1. 연구 포지셔닝 (Study Positioning)

이 연구는 다음과 같은 좁은 범주의 질문을 던집니다:

- 기성품(off-the-shelf) LLM이 일반적인(generic) ROS 레벨 도구만을 사용하여 PX4 드론을 어디까지 조작할 수 있는가?
- 어느 시점에서 프롬프트 전용 가이드(prompt-only guidance)만으로는 충분하지 않게 되는가?
- 드론에 특화된 MCP 설계가 정당화되기 전에 필요한 최소한의 비의미론적(non-semantic) 안정화 장치는 무엇인가?

의도된 논문 흐름은 단일체(monolithic)가 아니라 단계적(staged)입니다:

1. `C0`는 가공되지 않은 일반적인 ROS-MCP 베이스라인을 측정합니다.
2. `C1`은 프롬프트 컨텍스트만으로 베이스라인을 복구할 수 있는지 테스트합니다.
3. `C2`는 디스커버리(discovery) 단계에서 프롬프트가 복구하지 못한 로우 레벨 실패가 반복적으로 나타난 후에야 최소한의 고정된(frozen) 헬퍼 레이어를 추가합니다.

따라서 이 연구는 일반적인 ROS 도구 표면(surface)이 모든 드론 제어에 충분하다는 주장이 아닙니다. 이는 일반적인 도구 사용이 언제 취약해지는지, 그리고 어떠한 최소한의 추가 지원이 필요한지에 대한 경계 연구(boundary study)입니다.

## 2. 연구 질문 (Research Questions)

### RQ1. 실현 가능성 (Feasibility)

- 일반적인 ROS 레벨 도구 선택이 기본 PX4 초보자 비행 태스크를 지원할 수 있는가?

### RQ2. 실패 모드 (Failure Modes)

- 일반적인 도구 사용은 어느 지점에서 취약해지는가?
- 어떤 실패가 프롬프트로 복구 가능하며, 어떤 실패가 얇은 로우 레벨 지원 레이어를 필요로 하는가?

### RQ3. 전이 (Transfer)

- 시뮬레이션에서 작동하는 상호작용 패턴이 통제된 실내 실제 비행 환경으로 최소 규모로 전이될 수 있는가?

## 3. 주장 경계 및 현재 연구 상태 (Claim Boundary and Current Study Status)

현재 보존된 증거는 다음과 같은 좁은 범주의 주장만을 뒷받침합니다:

- 디스커버리(discovery) 페이즈는 왜 고정된 `C2` 헬퍼 서브셋이 전혀 필요한지를 정당화합니다.
- 현재 고정된 서브셋은 `setpoint_relay`, `mode_guard`, `abort_watchdog`입니다.
- 남아있던 `T3` 정사각형 패턴의 격차(설계 간극)는 타겟팅된 `C2` 배치로 별도 검증되었습니다.
- 현재 보존된 상태는 `official_sim`을 시작하기에 충분합니다.

현재 보존된 증거는 다음과 같은 더 강력한 주장은 아직 뒷받침하지 않습니다:

- `C2`가 최종 `T1-T4` 태스크 세트 전체에 걸쳐 완전히 검증되었다는 주장
- 실제 비행으로의 전이(real-flight transfer)가 이미 시연되었다는 주장
- 프레임/부호(frame/sign) 측면의 명시적이고 반복적인 실패가 보존된 헬퍼 고정의 근거 중 하나라는 주장

운영 관점에서 이 연구는 다음과 같이 진행될 수 있습니다:

1. `official_sim`
2. 프로모션 게이트(promotion-gate) 결정
3. 프로모션된 조건에 한해서만 `official_real` 진행

## 4. 범위 및 경계 (Scope and Boundary)

### 범위 내 포함 사항 (In Scope)

- `arm / disarm`
- `이륙(takeoff) / 호버링(hover) / 착륙(land)`
- 단거리 로컬 위치(local-position) 이동
- 시뮬레이션 내에서의 비행 중 궤도 수정 또는 중단(abort)
- 질문(clarification) 및 안전한 거부(refusal) 방어 기재
- 고정된 실내 스택 환경에서의 실패 특성화
- 시뮬레이션 프로모션 게이트를 통과한 후에 한정한 시뮬레이션-실제 단계 전이(sim-to-real transfer)

### 범위 제외 사항 (Out of Scope)

- 장애물 회피 (obstacle avoidance)
- 자율주행 중심의 높은 수준의 인지(perception-heavy autonomy)
- SLAM 또는 경로 계획 스택
- 기체 프레임 속도 제어를 메인 인터페이스로 사용하는 것
- `takeoff()`, `goto()`, `fly_square()`와 같은 의미론적(semantic) 드론 API
- 미션 실행기(mission executors), 행동 트리(behavior trees), 경로 생성기
- 공식 에피소드 간의 적응형 장기 메모리 구성

## 5. 고정 플랫폼 가정 (Fixed Platform Assumptions)

- OS: `Ubuntu 24.04`
- 미들웨어: `ROS 2 Jazzy`
- 시뮬레이터: `Gazebo`
- 오토파일럿: `PX4`
- 브릿지: `MAVROS`
- MCP 브릿지: `ros-mcp-server`
- 에이전트 런타임: `Gemini CLI`

공식 비교 단위는 에피소드당 하나의 완전히 새로운 Gemini CLI 세션을 뜻합니다.
라우팅된 모델은 `auto`로 유지됩니다. 실제 라우팅된 모델명은 에피소드 트레이스(trace) 기록에 남겨져야 합니다.

## 6. 제어 표면 경계 (Control Surface Boundary)

본 연구는 의도적으로 ros-mcp의 IMECE 전용 서브셋만 노출합니다.

| 카테고리 | 허용된 표면 | 제외된 표면 | 이유 |
| --- | --- | --- | --- |
| 상태 관측 (State observation) | `/mavros/state`, `/mavros/local_position/pose`, `/mavros/battery` | 임의의 ROS topics, 노드 그래프, 파라미터들 | 태스크 완료, 점수 측정, 안전 점검에 충분한 정보 제공 |
| 제어 출력 (Control output) | `/mavros/setpoint_position/local` | 속도 제어, 바디 프레임 제어, 미션 주제, 임의의 퍼블리시 타겟 | 본 연구를 로컬 위치(local-pose) 제어 수준으로 유지 |
| 서비스 (Services) | `/mavros/set_mode`, `/mavros/cmd/arming` | 이착륙 등 의미론적인 MAVROS 비행 서비스 일체 | 에이전트가 모드 순서 추론 및 서보(시동)의 책임을 보존하도록 함 |
| 일반 도구 계열 (Generic tool families) | topic/service introspection, subscribe, publish, call | 액션(actions), 파라미터, 특정 로봇 전용 도구, 관련 없는 표면 등 | 실패의 원인을 해석 및 특정(attribution) 가능하도록 제한함 |

향후 `official_sim` 실행에 사용될 공유된 일반 표면(shared generic surface)은 다음의 좁게 정의된 두 가지 측면에서만 안정화됩니다:

- 일반 도구는 과거의 스키마 구조 변경에 의한 이탈(drift) 실패 대신 잘못 입력된 `wait_for_previous` 필드를 정상적으로 허용합니다.
- `subscribe_for_duration`은 내부에 `first_msg`, `last_msg` 및 `summary`를 지닌 압축된 페이로드 구조로 반환해 줍니다.

이는 인터페이스 레벨의 안정화이지, 의미론적(semantic) 수준의 비행 프리미티브(primitive)가 아닙니다.

## 7. 조건 (Conditions)

| 조건 | 도구 표면 | 프롬프트 컨텍스트 | 헬퍼 레이어 | 의도된 역할 |
| --- | --- | --- | --- | --- |
| `C0` | 일반 ROS-MCP 도구만 | 연결 컨텍스트 외엔 없음 | 없음 | 가공되지 않은 일반적 베이스라인 |
| `C1` | `C0`와 동일 | 5가지 운영 사실 추가 제공 | 없음 | 프롬프트 전용 복구 시도 |
| `C2` | 동일한 일반 표면 | `C1`과 동일 | 고정된 최소 헬퍼 서브셋 | 최소한으로 요구되는 전송 및 안전 지원 |

### C0

`C0`는 드론 운용 힌트 없는 상태에서 반드시 실행 가능한 상태가 유지되어야 합니다.
따라서 조건 산출물(condition artifact)은 다음의 세 가지만을 수행합니다:

- 조건 이름을 명시함.
- 에이전트의 도구를 노출된 IMECE 전용 도구들로만 한정함.
- 에이전트가 행동을 취하기 전에 먼저 승인된 표면을 구조적으로 조사하라고 지시함.

이것은 실행 가능한 베이스라인이지 절대 불가능한 블라인드형(blind) 베이스라인이 아닙니다.

### C1

`C1`은 정확히 5가지 운영 사실을 추가합니다:

- 로컬 위치는 `ENU` 좌표계 축을 따릅니다.
- 모드를 일시적으로라도 전환하기 이전에 `OFFBOARD` 모드는 셋포인트 스트리밍 사전 전송 과정이 반드시 요구됩니다.
- 비행 중에는 간격 간 단절 없이 셋포인트 데이터 스트리밍이 지속되어야 합니다.
- 불명확한 점이 있을 땐 짧은 확인 질문을 유도해야 합니다.
- 최종 착륙 접근 시에는 `LAND` 모드를 선택적으로 지향해야 합니다.

`C1`은 "가장 좋은 최적의(best possible) 프롬프팅"을 고의적으로 표방하지 않습니다. 즉, 허용되는 가장 최소한 크기의 프롬프트 보정(repair) 수단입니다.

### C2

`C2`는 동일한 수준의 `C1` 기반 프롬프트 및 도구 표면을 유지한 상태에서, 반복된 디스커버리 페이즈 실패가 근거로 작용하는 고정된(frozen) 범위의 헬퍼 서브셋만을 얇게 추가(레이어드)합니다.

#### 허용된 헬퍼 카탈로그

- `setpoint_relay`
  - 에이전트가 마지막으로 검증된 대상 구조에 발행한 로컬 포즈 타겟을 `20 Hz` 주기로 유지하여 전송함.
- `frame_guard`
  - `ENU` 좌표계 기반의 로컬 포즈 관례를 노멀라이징(표준화/교정)하고, 명백히 일치하지 않는 프레임과 부호 방향 불일치 에러를 튕겨냄.
- `mode_guard`
  - 기체 접근 방식에 대한 가장 최소한의 안전 순서 모드를 강제함: 사전 스트리밍(prestream) -> `OFFBOARD` -> 시동(arm) -> 착륙모드(`LAND`)
- `abort_watchdog`
  - 타임아웃 지연 시나리오나 사용자가 발생시킨 런타임 종료/회피 이벤트에 대응하여 최종 `LAND` 모드 착륙 강제화.

#### 현재 고정된(Frozen) 서브셋

- `setpoint_relay`
- `mode_guard`
- `abort_watchdog`

`frame_guard`는 여전히 코드로 구현되어 있으나 현재의 분류기(classifier) 기준 하에 명백히 반복적인 프레임/방향 불일치 오류를 현재 디스커버리 감사 보고서에서는 증명하지 않아 활성 대상의 서브셋 고정 카테고리에 편입되지 않았습니다.

#### 금지된 헬퍼 동작

- 고도 자동 결정
- 자동 웨이포인트(waypoint) 또는 미션 경로 계산/생성 제공
- 사각형, 삼각형, 또는 특정 단일 반환점과 같은 기하학적 궤적 생성 기능 제공
- 다중 단계가 필요한 비행 과정을 세부 요소 숨김(hide) 없이 포장된 단 한 번의 호출로 조작하는 동작 트리 엔진이나 미션 추적기

## 8. 실패 분류 트리 (Failure Taxonomy)

### F1. 모호성 (Ambiguity)

- 불명확한 방향, 거리, 고도 수치 정보 또는 행동 일시 정지와 재시작 지점 기준 판단 누락.
- 추가 해명(clarification)이 필요하거나 혹은 에이전트 입장에서는 단호한 거절(refusal)로 판별되어야 할 입력 어휘 문맥.

### F2. 도구 및 인터페이스의 오용 (Tool or Interface Misuse)

- 적절하지 않은 통신 대상, 즉 주제(topic) 및 서비스 엔드포인트 선택.
- 올바르지 않은 ROS 인터페이스 구조 활용.
- 사용 도구의 매개변수 값 조작 시 부적절한(invalid) 처리.

### F3. 메시지 혹은 좌표계 프레임의 문제 (Message 단Error)

- 잘못된 구조 필드 메시지 발행, 지원되지 않는 값 단위의 지정, 로컬 `ENU` 형식에 위배되는 방향 부호 체계 사용.

### F4. Offboard 및 타이밍 실패 제어 (Offboard or Timing Failure)

- 불충분하게 제공된 사전 스트리밍 모드 시작 준비 절차.
- 빈번하거나 중도 누락된 희소한(sparse) 셋포인트 스트리밍 유지 이슈.
- 순서, 또는 지연 전송 등의 타이밍이 빗나갔기 때문에 빚어진 `OFFBOARD` 컨트롤 탈락 및 런타임 무시 현상.

### F5. 복구 불가능 요소 또는 안전상의 강제 정지 (Recovery or Safety Abort)

- 런타임 소멸(타임아웃).
- 관찰 운영자에 의해 발생된 즉각적인 수동(매뉴얼) 개입 상황 발생.
- 헬퍼 중재에 의해 유발된 강제 착륙 방어 체계(watchdog).
- 운영 측 궤도 이탈 수정에 대응 시 실패 결과 돌출 현상 발생(failed interrupt handling).

## 9. 태스크 세트 준비 (Task Set)

### 시뮬레이션 환경용 태스크 (Simulation Tasks)

| 태스크 번호 | 타이틀명 | 기준 프롬프트(Canonical prompt) | 실험적 의의(목적) |
| --- | --- | --- | --- |
| `T1` | 이륙 호버 시도 간 착륙(Takeoff Hover Land) | `Take off to one meter, hover for five seconds, then land.` | 베이직 속성의 Offboard 시작 과정, 기본 횡단(hovering), 종착 컨트롤 시험 |
| `T2` | 짧은 단구간 번역 이동 (Short Translation) | `Take off, move one meter forward, hover, and land.` | 매우 좁은 로컬 단기 거리에 대한 위치 이동 평가 |
| `T3` | 정사각형 궤도 횡단 (Square Pattern Flight) | `Take off, fly a square with one-meter sides, return near the start, and land.` | 점 간 위치 제어 패턴 기반의 순차적인 복수의(다중의) 로컬 이동 지점 이동 시퀀스 추론 시험 |
| `T4` | 비행 중 인터럽트 끼어들기 대응 체계 (Mid-flight Interrupt Handling) | `Take off and move forward one meter.` | 간섭 대응, 명령 보정 교체 지시 수용, 최후 통제를 포함한 정상 안전 착륙 처리 여부 평가 |

`T3`는 이미 정의된 월드 절대 원점 기반으로 가정한 후 움직임 거리를 판단하는 목적지가 아닌 가장 최초 단계 도출 기준의 로컬 좌표 포즈를 추정 삼아 목표로 이동하게 유도되었습니다.
`T4`는 확정적(결정적)인 고정 보정형 프롬프트(deterministic correction prompts) 패턴 구조를 사용합니다:

- 홀수 에피소드 진행 회차 시점: `Stop there.`
- 짝수 에피소드 진행 회차 시점: `Land now.`

### 실제 비행 환경 준비 대상 태스크 (Real-flight Tasks)

- `R1`: takeoff-hover-land (이륙-호버링-착륙 과정)
- `R2`: short translation (짧고 단편적인 로컬 수평 이동 과정)

`T4`는 본질적으로 안전성 점검 및 시나리오 진행 가능 여부를 통째로 가늠하는 시뮬레이션용 한정 전용 게이트 역할을 담당하며 공식적으로 취급받는 실제 실가동 비행 점검 태스크 셋 리스트에는 등재되지 않습니다.

## 10. 성공 판별 기준 (Success Criteria)

### 필수 공유 기준 (Shared)

- 에피소드당 최대 허용 대기 종료 시간: `120 s`
- 모든 측정 대상 에피소드 진행 개시별 완전히 신규 생성된 세션 상태를 기초 자산으로 사용하는 신규 Gemini 런타임.
- 런타임 결과 로깅 데이터 모음집 및 개별 과업 맞춤형 성공 룰셋 기반의 통합성 평가 성공 판정 수행.
- 각 에피소드는 러너(runner)가 정규화하여 강제로 배치한 육상 착륙/시동 해제 상태라는 완벽한 시작 초기 베이스라인 시점을 거점으로 함.

### T1 / R1

- 약 `1.0 m`의 높이 접근 시도 수행 성공 목표
- 달성 고도권에서 대략 `5초`의 비행 유지 시도 수행 성공 목표
- 비상 파손 요소 없이 안전한 궤적 통제 아래로 착륙하는 목표

### T2 / R2

- 국소 범위(local translation) 요구치인 대략 `1.0 m` 목표점을 정조준하고 접근하는 수행
- 최종 이동 거리에 대해 판단 오차범위 `<= 0.25 m`
- 비상 파손 요소 없이 안전한 궤적 통제 아래로 착륙하는 목표

### T3

- 이륙 직후 공중 정지 상태의 유지, 3개의 모서리 경유, 첫 출발 정지 궤도로 순차 복귀를 순서대로 준수 및 달성
- `1 미터` 길이 단위 변을 지닌 기준 로컬 `ENU` 기반, 시작 포인트 연계형 정사각형 좌표 체계 반영 활용
- 시작 출발 고도 및 위치 체계 인근 수준으로 복귀 달성
- 비상 파손 요소 없이 안전한 궤적 통제 아래로 착륙하는 목표

### T4

- 요구된 명령 변경 알림 프롬프트 지시에 대해 안전하게 순차 대처 수행 성과 발휘
- 중단/보정 의도의 본질에 맞아떨어지는 최종 도착 상태 종료 수행 증명 여부
- 추가 개입 수단(운영자의 조작기 사용 등) 없이 시나리오 진행 종단

## 11. 실험 전개 국면 상세 기술 (Experimental Phases)

### 디스커버리 조기 점검 실험 (Discovery Pilot)

- 조건군(Conditions): `C0`, `C1`
- 대상 수행 목록(Tasks): `T1-T4`
- 에피소드 시도 세트 수(Repetitions): 각 `5`
- 목표: 관례적으로 반복 등장하는 오류 인자들을 색출하고, 현재 단계에서 `C2` 구성 투입 검증 착수가 필요한지 정당성을 조사 판단.

### C2 헬퍼 구성 고정 확인 규칙 방안 (C2 Freeze Confirmation Rule)

- 조건 변화가 포함된 개별 컴포넌트 추가 등은 오로지 이러한 파일럿형(pilot) 배치 단계를 진행하는 막간 사이에서만 교정 승인 허가 조치.
- 정사각형 궤도 횡단 방식이 `T3`라는 지정 식별자로 체계가 격상 및 고정된 전제하에, `C2` 검증으로 기재된 일괄 확인용 작업 일체는 `T1-T4`의 점검 구역 일체를 무조건 포함하여 소화.
- 완전히 균형 잡힌 구조 대칭형(symmetric) 전체 `C2` 점검 배치 규격 모델 구성 기준: `C2 x T1-T4 x 5`
- 다만 본 연구에서 보존되는 관련 서류 속 공식 확정된 구성 기록 자체는 조금 더 타겟에 맞춤화 됨: 최초 디스커버리 분석 도출 내용과 `C2:T3` 맞춤 타겟 검증 구조로 한정 적용.

### 공식 시뮬레이션 과정 시제 평가 (Official Simulation)

- 적용 조건군: `C0`, `C1`, `C2`
- 반영 수행 목록: `T1-T4`
- 세트당 반복 재연 검증 수: `10`
- 실험이 해당 페이즈 선을 넘나드는 중에는 어떠한 프롬프트 내용, 헬퍼 세트 로직 적용 구성 정책 일체 건드리지 않고 제한된 고정 모드 유지.

### 실제 하드웨어 대상 운용 승격 여부 (Real-flight Promotion Gate)

다음에 제시한 4가지 관문 평가 요건 일체를 누락 없이 완전히 만족시킨 환경 조건군만 중점 대상으로 삼고 윗 번호로의 최고 순위만 선별 프로모션 승급 대상으로 지정 (지원 계층이 낮은 경우 우대함):

- `T1` 결과의 객관적 성공 판별률 `>= 8/10`
- `T2` 결과의 객관적 성공 판별률 `>= 8/10`
- 비행 중 회피, 인터럽트 등 궤도 보호가 기반된 안전성 종료가 확보된 `T4` 성공 판별률 `>= 8/10`
- 게이트 평가 배치 수행 전 구간에 걸친 중대 보안/파손 급 치명적 실패 횟수: `0`

### 공식 실제 환경 체재 전면 가동 체계 (Official Real Flight)

- 가장 최고 순위로 게이트 테스트를 통과해 자격을 갖춘(promoted) 조건만 실험 전대에 투입
- 이수 완료 평가군(Tasks): `R1`, `R2`
- 연동 시험 전개 횟수: 각 `5`
- 인입 및 추적이 지원되는 실내 모션 캡처 환경(mocap environment) 제한적 사용

### 현재 프로세스 전개 진행률 (Current Execution Status)

- `discovery` 환경 전수 조사, `c2_freeze` 체계 수렴 단계, `official_sim` 평가 수행 모두 러너 시스템에 오토메이션으로 편입 관리 대상 상태
- 현재 실제 드론 투입 비행 테스트 건은 `run-real-episode` 단건 구동 단일 에피소드 스캐폴드(뼈대) 환경 제공만 진행
- 현재 시점에서 보존된 기록 환경을 토대로 곧바로 `official_sim` 파이프라인 진입 절차 가동 가능 상황
- 최후의 `official_real` 진행 개시령은 무조건 상기 기술한 프로모트 관문 심사가 적합 판정으로 채점 종료된 후 개시 요망

## 12. 저장소 구조 배치 맵 정리 (Repository Map)

### 관련 지식 기술 문서 파트 (Documentation)

| 경로 | 기여 역할 |
| --- | --- |
| [`docs/imece/implementation-kor.md`](./implementation-kor.md) | 주요 연구 규격 사양 전서 및 통합 동작 뼈대 맵 목록 |
| [`docs/imece/experiment-record-kor.md`](./experiment-record-kor.md) | 진행된 보존용 실험 진행 이력, 원시 취합 데이터 결과 정리, 논문 구성 배포판 형태의 구문 문장 해석본 제공 |
| [`docs/imece/runbook-kor.md`](./runbook-kor.md) | 런타임 제반 스크립트 실행 요소, 커맨드 사용 기법, 명령어 부속 인자 활용 사례 |
| [`docs/imece/agent-development-guide-kor.md`](./agent-development-guide-kor.md) | 문서를 확인하는 미래의 에이전트 인공지능이 취해야 하는 점검 방식, 결과 도출 지표 파악 및 갱신에 관한 지침 집 |
| [`docs/imece/design-rationale-kor.md`](./design-rationale-kor.md) | (단종 조치) 옛 디자인 사양 설명 구조 리다이렉트 파일; 내용 일체 본 문서 및 다른 주류 파일에 속입됨 |

### 설정 아티팩트 (Configuration Artifacts)

| 경로 | 기여 역할 |
| --- | --- |
| [`config/imece/c0.md`](../../config/imece/c0.md) | 가장 원시적인 일반 도구 사용의 조력을 제공하는 기본 프롬프트 베이스 |
| [`config/imece/c1.md`](../../config/imece/c1.md) | 프롬프트만으로 비행 교정 수단 제시를 시도하는 복원 도모 성질의 질문 블록 |
| [`config/imece/c2.md`](../../config/imece/c2.md) | 연구 대상에 주입될 `C2` 기반의 공용 헬퍼 기능 가이던스 파편 코드 |
| [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json) | 고정된 헬퍼 레이어 서브셋 설정이 녹아 있는 런타임 구동 반사경(mirroring 파일) |
| [`config/imece/gemini-policy.toml`](../../config/imece/gemini-policy.toml) | Gemini 활용을 위해 통제용 정책 도구 옵션들이 삽입된 속성 서식 |

### 서버 구동 제어부 (Runtime Code)

| 경로 | 기여 역할 |
| --- | --- |
| [`ros_mcp/imece/server.py`](../../ros_mcp/imece/server.py) | IMECE 범주 연구 도메인 전용의 통합 ros-mcp 서버 연동 인터페이스 진입 지점 |
| [`ros_mcp/imece/constants.py`](../../ros_mcp/imece/constants.py) | 허가된 사용 통신 토픽, 구동 서비스 내역, 지원 헬퍼 지정명, 그리고 베이직 기본값 모음 단지 |
| [`ros_mcp/imece/boundary_tools.py`](../../ros_mcp/imece/boundary_tools.py) | 방어요인이 적용 필터링된 기반 제어 툴과 용량이 최소 사이즈가 압축 요약 데이터 수집 청취자(subscription) 코드군 |
| [`ros_mcp/imece/helpers.py`](../../ros_mcp/imece/helpers.py) | `setpoint_relay`, `frame_guard`, `mode_guard`, `abort_watchdog` 소스코드 위치 |
| [`ros_mcp/imece/config.py`](../../ros_mcp/imece/config.py) | 대상 업무(태스크) 사양 모듈 조립부 공간, 프롬프트 동적 컴파일 영역, 그리고 `T4` 태스크용 고정형 확정 제어 신호 인젝션 제공 모듈 |
| [`ros_mcp/imece/gemini.py`](../../ros_mcp/imece/gemini.py) | 세션 턴 체제 기반으로 작동되는 Gemini CLI 응답 대기 및 턴 진행과 로깅 기록 흔적 일괄 처리 담당부 |
| [`ros_mcp/imece/rosbridge.py`](../../ros_mcp/imece/rosbridge.py) | rosbridge 채널 네트워크단 요구 및 스트리밍 관측과 모니터용 통합 헬퍼 체계 |
| [`ros_mcp/imece/monitor.py`](../../ros_mcp/imece/monitor.py) | 런타임 기반 상태 정보, 배점 처리를 위한 로깅 현황 추적, 진단 스탯 확보 전반 담당 관찰자 모듈 |
| [`ros_mcp/imece/scoring.py`](../../ros_mcp/imece/scoring.py) | 구동 중, 또는 사후 감사(audit) 진행 단계 모드 일체에 적용 가능한 융통적 목표 채점 체계 |
| [`ros_mcp/imece/analysis.py`](../../ros_mcp/imece/analysis.py) | 실패 패턴 분석 체계, 허용 가능한 헬퍼들의 집합 선택 로직 모듈, 오딧(에세이)형 사후 재정산 보고 생명선 코드 |
| [`ros_mcp/imece/runner.py`](../../ros_mcp/imece/runner.py) | 커맨드라인에서 단일 에피소드, 통배치 실험, 페이즈 체계 전반 분석부터 평가 진행 등 실험 일거수일투족을 진행할 진입 루트 담당체 |

### 스크립트 도구들 (Scripts)

| 경로 | 기여 역할 |
| --- | --- |
| [`scripts/imece/setup_gemini_project_mcp.sh`](../../scripts/imece/setup_gemini_project_mcp.sh) | 지역적 단위 범위의(project-local) Gemini MCP 환경 준비 제반 설치 도우미 체제 |
| [`scripts/imece/start_sim_stack.sh`](../../scripts/imece/start_sim_stack.sh) | PX4, MAVROS, 및 가교 구성망(rosbridge) 기반 시동 켜기 묶음 |
| [`scripts/imece/stop_sim_stack.sh`](../../scripts/imece/stop_sim_stack.sh) | 단독 시뮬레이션 환경 안전 종료 묶음 |

### 테스팅 단위 도구 (Tests)

| 경로 | 기여 역할 |
| --- | --- |
| [`tests/imece/test_boundary_surface.py`](../../tests/imece/test_boundary_surface.py) | 안전 경계 인지 제어 허용 리스트 구조 검증용 패키지 |
| [`tests/imece/test_boundary_tools.py`](../../tests/imece/test_boundary_tools.py) | 압축 정렬된 전송 내용 구성 정보 수집 데이터 확인 테스터 |
| [`tests/imece/test_prompts.py`](../../tests/imece/test_prompts.py) | 프롬프트 정규 결합 상태 점검과 테스크 전용 명령 부여 이상 점검 |
| [`tests/imece/test_helpers.py`](../../tests/imece/test_helpers.py) | 헬퍼 보조 추가 계층들의 결함성 점검 |
| [`tests/imece/test_analysis.py`](../../tests/imece/test_analysis.py) | 시스템 사유 발생 시 실패 원인 파악 및 오딧 진행 결석 점검과 구성망 고정 파악 로직 확인용 테스터 |
| [`tests/imece/test_runner_batch.py`](../../tests/imece/test_runner_batch.py) | 작업 큐 배치 실행 단위 실험 모듈과 데이터 산출물 제작 구조 무결성 점검 체제 |
| [`tests/imece/test_gemini.py`](../../tests/imece/test_gemini.py) | Gemini 러너 호환성 융합 상태 연동 점검 도구 |
| [`tests/imece/test_policy.py`](../../tests/imece/test_policy.py) | Gemini 폴리시 로딩 절차 무결성 판단 구조 검토 앱 |

### 배출물 보존소 (Artifacts)

`artifacts/imece/<batch_id>/` 경로의 위치는 모든 종류의 배치 정보 산출 거점 루트를 일컫습니다.
개별적인 단일 에피소드 출력 내용은 다음을 포괄합니다:

- `prompt.txt`
- `gemini.jsonl`
- `gemini.stderr.log`
- `monitor.jsonl`
- `metrics.json`
- `metadata.json`
- `rosbag/`

단독 배치 수준으로 총합하여 생성되는 출력 내용물은 다음을 포괄합니다:

- `batch_state.json`
- `analysis.json`
- `audit.json`

## 13. 메트릭스 산출, 메타 구조물 정보, 그리고 로깅 구조 (Metrics, Metadata, and Logging)

### 메인 분석 평가 기준 수치형 정보 (Primary Metrics)

- 임무 달성 확률(task success rate)
- 사람 간섭 없이 자동으로 도출된 자체 임무 성공 도달률
- 시간 소모 비용

### 부가적 파악 및 추가 활용 지표 (Diagnostic Metrics)

- 태스크 종료 판정에 이르는 동안 왕복된 질문 등 소요 턴수(turns counts)
- 역질문 사용 및 소명 파악 횟수
- 도구 체제 접근 및 투입 사용 횟수 지정
- 권한 밖이나 오타 등으로 허용 안 된 부적절한(invalid) 도구 점유 사용 빈도
- `OFFBOARD` 환경 접속 요청 이후 리젝 및 오류 거절 개수 파악
- `OFFBOARD` 연결은 지속됐으나 누락/드롭되어 이탈하는 현상 빈도수 파악 측정
- 진입 성공 후 의미 있는 유효 제어 동작 수행 최초 발생까지의 지연 현상 값 수치
- 스트림 누락 발생 또는 입력 지연 등으로 지체된 가장 높은 최대 세팅 발생 폭 수치 (max setpoint gap)
- 최종 착륙 목표지에 대한 팩트와의 오차 차트율 값
- `T3` 단계 중 사각형 형태 경유 거점 경유 기록 현황 및 도착(completion flag) 증명 확인 절차

### 반드시 포함되어야 할 런타임 수반 증명 기록 구조 체계 (Required Runtime Metadata)

- 베이스 리포지토리의 최종 투입 해시 커밋 기준 SHA 문자열
- ros-mcp 저장소 관할 최종 투입 환경 커밋 기준 SHA 문자열
- 적용 PX4 환경 버전 코드 기준 SHA 문자열
- Gemini 기반 모델 CLI 구성 버전 값
- 실제로 작동 및 반영 도출된 라우팅 처리 모델명
- 현 MAVROS 적용 버전 기록
- 현 Gazebo 사용 환경 프로그램 에디션
- 적용 중인 ROS 배포반 종류(distro)

참고: 오래 전 가장 처음 시도되어 채취, 보존된 발견형 산출물 자원(discovery)에는 위의 윗선별 세부 기록(런타임 메타 수집 구조)이 온전하게 구축 반영되기 이전의 구물입니다. 때문에 시스템이 과거를 임의로 허위 사실을 유추하여 채워버리지 않고 팩트만을 남겨 두어야 합니다.

### 로깅 시 보존되어야 할 필수 구역 정보들 (Logging Requirements)

- 최초 초기 턴으로 보낸 풀 스케일급 프롬프트 전면 문자형
- 재확인 또는 해명 요청 및 상황 대응의 세부 기록 등
- Gemini 산출 도출 구조 아웃풋
- 세부 단위 시스템 도구 트리거 및 반영 응답 구조적 트레이스(trace)
- ROS 체제 기반 호출 이력 전반과 셋포인트 입력 내역들 정보 모음집
- 궤적 진행에 따른 포즈(pose) 위치/자세 구조 정보 로그들
- 일괄 단위 기록이 모여있는 배치 레벨 결과본 `analysis.json`
- 일괄 단위 기록이 모여있는 배치 레벨의 점검 감사본 데이터 파일 `audit.json`

## 14. 실증 절차 및 안전 최우선 원칙 (Procedure and Safety)

### 에피소드 진행 단계별 매뉴얼 (Episode Procedure)

1. 모든 진행은 언제나 시뮬 등 비행 가상 환경 및 실 가동 체제가 무결 조건으로 완전히 깨끗하게 초기 상태로 갱신된 것을 점검 및 반영 확인.
2. 각 구간 단계인 `PX4 <-> MAVROS <-> ROS2 <-> ros-mcp` 통신 링크 환경 및 파이프라인 무결 확인 점검.
3. 구동 전 현재 기기의 시스템이 지정된 저장소 커밋으로 반영, 유지된 상태인지 갱신 증명.
4. 모든 행적 로깅과 더불어 rosbag 형태의 전방위 정보 수집 체제를 가동 켜기 및 시작 준비 돌입.
5. 오염 안 된 백지의 신규 상태 Gemini 모델 세션을 구동 호출 개시.
6. 선발 초기 환경 설정 프롬프트 패키지 묶음 구조 지시 주입 처리 시작.
7. 모델 환경으로부터 모호성 해결 혹은 답변이 요구된 점검사항 돌출 시, 단 한 문장 안건 대응 지침의 원칙을 바탕으로 질의수렴 대처 진행 응답 실시.
8. `T4` 태스크형 미션에 도달 지정 구역 접근 시, 계획상에 정의된 스케줄 확정형 강제 명령 인터럽트 문장 투입 강제.
9. 그 어떠한 멈춤 처리 행위도 정상 임무 달성, 스스로의 거부 반환, 작업자 측에서 치명적 결함으로 직접 조종기를 빼앗은 경우 개입 전개(takeover), 워치독 프로그램이 오판정 착륙을 직접 수행한 경우, 혹은 최고 허용된 한계 러닝 시간 도달이라는 소진 상태만 종단.
10. 도출 결괏값 연산을 시작 진행하여 일괄 배치형 단위의 수치 평가 분석과 요약 데이터 기록문 파일로 추출 보존 작업 매듭 처리 완료.

### 실제 하드웨어 대상 운용 필수 안전 사항 (Real-flight Safety)

- 조종기(RC) 혹은 QGC 모드와 같이 항상 모든 것을 셧다운 처리하거나 우선 지휘권을 되찾는 물리적 수준의 강제 개입 시스템 작동 준비 체제 일체 필수.
- `abort_watchdog`은 타임 아웃에 도달 혹은 안전 시스템 등에서 거절된 경로로 유보 진행 시에 즉시 대응한 `LAND` 형태의 강제 접지로 귀속 모드 호출 전개 의무화.
- 실제 투입 기체용 환경 구성은 반드시 측정 캡처를 동원한 실내 물리 방어 그물망 부피 구조 안에서 수행.
- 강제로 통제된 실험 영역 봉투(Fixed task envelope):
  - 높이 고도: `1.0 m` 상공
  - 수평 거리: `1.0 m` 내경
  - 호버링(대기) 목표 체공 달성: `5 s`
- 실제 테스트 영역의 보존 및 허용 천정 범위는 현장에서 직접 기록 및 검안 점수 등 수동 측정하고 실제 시동 이륙 전 모든 평가 보고가 전제되어 승인됨이 선결.
