# Workflow Probe · from Voice Shift Probe

[![웹 앱 검증](https://github.com/7065616b/voice-shift-probe/actions/workflows/workflow-probe.yml/badge.svg)](https://github.com/7065616b/voice-shift-probe/actions/workflows/workflow-probe.yml)

**조건을 바꾸면 평소에는 드러나지 않는 오류를 찾을 수 있을까?**

게임에서 상대의 특이한 반응을 관찰한 경험을 음성 탐지 연구로 옮겼고, 같은 원리를 웹 앱의 자동 오류 검증으로 확장했습니다. 현재 개발 방향은 **[Workflow Probe](workflow-probe/)**입니다.

정렬, 연속 클릭, 새로고침을 수행하면서 금액과 저장 내역이 지켜야 할 약속을 비교합니다. 직접 만든 앱 5개 버전에서 45회 검사하고, 변경 전후 수치·화면·실행 추적을 남깁니다. 이는 학습된 AI 모델이나 실제 서비스의 정확도 평가가 아닌, 재현 가능한 조건 변화 검증 프로토타입입니다.

| 관찰 | 조건 변경 전 | 조건 변경 후 |
|---|---|---|
| 정렬 후 합계 오류 | 32,000원 | 29,000원 |
| 연속 클릭 중복 저장 | 0건 | 2건 |
| 새로고침 후 표시 누락 | 1건 | 0건 |

공개 저장소에는 코드와 수치 기록을 담습니다. 화면과 실행 추적은 로컬에서 검사를 실행하면 생성됩니다.

- [실행 방법과 검사 원리](workflow-probe/README.md)
- [원본 관찰](workflow-probe/report/results.json) · [독립 평가](workflow-probe/report/evaluation.json)
- [설계](workflow-probe/workflow/plan.md) · [QA](workflow-probe/workflow/qa.md)
- [이전 음성 연구와 한계](VOICE_RESEARCH.md): 코드·증거·재현 절차는 기존 위치에 보존했습니다.

이 저장소의 이름 `voice-shift-probe`는 연구의 출발점을 기록하기 위해 유지합니다.
