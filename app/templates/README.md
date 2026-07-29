# Templates 디렉토리

## 목적

AI 코딩(Opus 4.8) 시 참고할 코드 스켈레톤

---

## 사용 방법

### 1. 템플릿 읽기
```
templates/{파일명}.py를 참고해서 oma/{경로}/{파일명}.py를 구현해줘.
```

### 2. TODO 구현
- 템플릿에는 `# TODO: 구현` 주석
- AI가 TODO 부분만 구현
- 구조는 템플릿 그대로 유지

### 3. 변경 이력 작성
- 템플릿의 `[날짜] [작성자]` 부분을 실제 날짜/이름으로
- 구현 내용 기록

---

## 템플릿 목록

| 파일 | 모듈 | 설명 |
|------|------|------|
| `config.py` | oma/utils/config.py | 설정 로더 |
| `secrets.py` | oma/utils/secrets.py | Secrets Manager |
| `exceptions.py` | oma/utils/exceptions.py | 예외 클래스들 |
| `llm_client.py` | oma/converter/llm_client.py | LLM API 호출 |
| `dictionary_builder.py` | oma/dictionary/builder.py | 딕셔너리 생성 |
| `fragmenter_splitter.py` | oma/fragmenter/splitter.py | 매퍼 분할 |
| `ValidationService.java` | java-validator/.../ValidationService.java | Java 검증 서비스 |

---

## 템플릿 작성 원칙

### 1. 구조만, 구현은 TODO
```python
def method(self):
    """Docstring은 완전히"""
    # TODO: 구현
    pass
```

### 2. 타입 힌트 필수
```python
def method(self, param: str) -> Dict[str, Any]:
    pass
```

### 3. 주석으로 가이드
```python
"""
TODO:
1. 단계 1
2. 단계 2
3. 단계 3
"""
```

---

## 버전
- 버전: 1.0
- 작성일: 2026-07-27
