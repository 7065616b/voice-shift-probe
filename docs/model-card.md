# 연구 구현 v0.1 모델 카드

## 구성

- 모델 유형: 고정된 사전 학습 음성 판별기 + 배속별 점수 평균 래퍼.
- 기반 모델: Speech-Arena-2025 / DF_Arena_1B_V_1. 신규 학습·미세 조정 없음.
- 입력: FFmpeg로 디코딩한 16kHz 단일 채널 음성. 최소 4096표본.
- 변환: 원본, pitch-preserving atempo 0.8 / 1.0 / 1.25.
- 출력: 조건별 raw spoof score, 원본·0.8·1.25의 산술 평균, 구간 수, 반복 특징.
- 1.0배: 변환 영향 대조 조건. 평균에는 포함하지 않음.
- 특징: 25ms 프레임/10ms 이동, 강약 및 24개 주파수 대역의 상대 모양. 원래 시간으로 환산한 0.25~2초 자기상관. 특징은 진단용이며 점수 평균의 추가 학습 입력이 아님.
- 호흡 탐지, 질문에 대한 실시간 응답 검증, 음악 성분 판별은 이 래퍼에 없음.

## 별도 준비해야 하는 기본 실행 폴더

```text
baseline_run/
  script.py
  model/
    df_arena_1b/
      __init__.py
      config.json
      modeling_antispoofing.py
      configuration_antispoofing.py
      feature_extraction_antispoofing.py
      backbone.py
      conformer.py
      pytorch_model.bin
      facebook/wav2vec2-xls-r-1b/config.json
```

기본 script의 최상위 import 때문에 librosa, torchaudio, demucs, tqdm도 설치해야 합니다. 모델 코드와 가중치는 원 제작자 배포처 및 이용 조건을 따릅니다. 공식 기본 코드의 해시가 다른 배포본은 이 엄격한 어댑터에서 거부합니다.

- 기본 script SHA256: `c17d776b7c17c2d70f1e55c2186ea54f0af8695dcdf07a106523cd80213aed9e`
- DF-Arena 가중치 SHA256: `780bc14fd4c15e65d58efdef728427cf03cd29cd60be528e97badf8c89087988`
- 원래 가중치 리비전: `fb6ce85de12c2c5a509d89114adaf827dd75f49f`
- [원 제작자 가중치](https://huggingface.co/Speech-Arena-2025/DF_Arena_1B_V_1/blob/fb6ce85de12c2c5a509d89114adaf827dd75f49f/pytorch_model.bin)

## 검증 범위

2026-09-29 GPU 실행은 `evidence/frozen/gpu_inference.py`가 수행했습니다. 공개 패키지의 새 래퍼는 해당 처리를 재사용하도록 구성하고 CPU에서 변환·결합·반복 특징·증빙 검산을 확인했습니다. 공개 정리 과정에서 새 래퍼의 전체 GPU 실행은 수행하지 않았습니다.

EER은 동점 점수를 묶어 ROC 교차점을 선형 보간합니다. 대회의 최근접 ROC 지점 EER 및 ADS와 동일한 계산이 아닙니다. 평균 점수와 반복 특징의 실사용 판정 기준은 확정하지 않았으며, 입력 음질과 생성기 변화에 대한 일반화도 확인하지 못했습니다.
