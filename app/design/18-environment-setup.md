# 환경 구성 및 사전 점검

## 목적

OMA 실행 전 필수 환경 점검 및 매퍼 파일 사전 검사

---

## 1. 환경 점검 스크립트

### check_environment.sh

```bash
#!/bin/bash

echo "========================================="
echo "OMA Environment Check"
echo "========================================="
echo ""

EXIT_CODE=0

# 1. Python 3.11 체크
echo "[1/6] Checking Python 3.11..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    if [[ $PYTHON_VERSION == 3.11.* ]]; then
        echo "✓ Python 3.11 found: $PYTHON_VERSION"
    else
        echo "✗ Python 3.11 required, but found: $PYTHON_VERSION"
        EXIT_CODE=1
    fi
else
    echo "✗ python3 not found"
    EXIT_CODE=1
fi
echo ""

# 2. Java 11+ 체크
echo "[2/6] Checking Java 11+..."
if command -v java &> /dev/null; then
    JAVA_VERSION=$(java -version 2>&1 | head -n 1 | awk -F '"' '{print $2}')
    JAVA_MAJOR=$(echo $JAVA_VERSION | cut -d'.' -f1)
    if [ "$JAVA_MAJOR" -ge 11 ]; then
        echo "✓ Java $JAVA_VERSION found"
    else
        echo "✗ Java 11+ required, but found: $JAVA_VERSION"
        EXIT_CODE=1
    fi
else
    echo "✗ java not found"
    EXIT_CODE=1
fi
echo ""

# 3. Maven 체크
echo "[3/6] Checking Maven..."
if command -v mvn &> /dev/null; then
    MVN_VERSION=$(mvn --version 2>&1 | head -n 1 | awk '{print $3}')
    echo "✓ Maven $MVN_VERSION found"
else
    echo "✗ mvn not found"
    EXIT_CODE=1
fi
echo ""

# 4. PostgreSQL client 체크
echo "[4/6] Checking PostgreSQL client..."
if command -v psql &> /dev/null; then
    PSQL_VERSION=$(psql --version | awk '{print $3}')
    echo "✓ psql $PSQL_VERSION found"
else
    echo "⚠ psql not found (optional, but recommended)"
fi
echo ""

# 5. AWS CLI 체크
echo "[5/6] Checking AWS CLI..."
if command -v aws &> /dev/null; then
    AWS_VERSION=$(aws --version 2>&1 | awk '{print $1}' | cut -d'/' -f2)
    echo "✓ AWS CLI $AWS_VERSION found"
else
    echo "✗ aws cli not found"
    EXIT_CODE=1
fi
echo ""

# 6. Python 패키지 체크
echo "[6/6] Checking Python packages..."
REQUIRED_PACKAGES=(
    "anthropic"
    "boto3"
    "psycopg2"
    "lxml"
    "pytest"
)

MISSING_PACKAGES=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import $pkg" 2>/dev/null; then
        echo "✓ $pkg installed"
    else
        echo "✗ $pkg not installed"
        MISSING_PACKAGES+=($pkg)
        EXIT_CODE=1
    fi
done
echo ""

# 결과 요약
echo "========================================="
if [ $EXIT_CODE -eq 0 ]; then
    echo "✓ All checks passed!"
    echo "========================================="
else
    echo "✗ Some checks failed"
    echo ""
    echo "To fix:"
    
    if [[ ! -z "${MISSING_PACKAGES[@]}" ]]; then
        echo "  pip install -r requirements.txt"
    fi
    
    echo ""
    echo "========================================="
fi

exit $EXIT_CODE
```

### 실행
```bash
chmod +x check_environment.sh
./check_environment.sh
```

---

## 2. Python 3.11 심볼릭 링크 설정

### macOS/Linux

```bash
#!/bin/bash
# setup_python311.sh

echo "Setting up Python 3.11 as default python3..."

# Python 3.11 위치 찾기
PYTHON311_PATH=$(which python3.11)

if [ -z "$PYTHON311_PATH" ]; then
    echo "✗ Python 3.11 not found"
    echo "Install with: brew install python@3.11  (macOS)"
    echo "            or: sudo apt install python3.11  (Ubuntu)"
    exit 1
fi

echo "Found Python 3.11 at: $PYTHON311_PATH"

# 현재 python3 확인
CURRENT_PYTHON3=$(which python3)
echo "Current python3 at: $CURRENT_PYTHON3"

# /usr/local/bin/python3 심볼릭 링크 생성
LINK_PATH="/usr/local/bin/python3"

if [ -L "$LINK_PATH" ]; then
    echo "Removing existing symlink: $LINK_PATH"
    sudo rm "$LINK_PATH"
fi

echo "Creating symlink: $LINK_PATH -> $PYTHON311_PATH"
sudo ln -s "$PYTHON311_PATH" "$LINK_PATH"

# 확인
echo ""
echo "Verification:"
python3 --version

# pip3도 설정
PIP311_PATH=$(which pip3.11)
if [ ! -z "$PIP311_PATH" ]; then
    LINK_PIP_PATH="/usr/local/bin/pip3"
    if [ -L "$LINK_PIP_PATH" ]; then
        sudo rm "$LINK_PIP_PATH"
    fi
    sudo ln -s "$PIP311_PATH" "$LINK_PIP_PATH"
    echo "pip3 --version: $(pip3 --version)"
fi

echo ""
echo "✓ Setup complete!"
echo "Now 'python3' will use Python 3.11"
```

### 실행
```bash
chmod +x setup_python311.sh
./setup_python311.sh
```

### PATH 우선순위 설정 (대안)

```bash
# ~/.bashrc 또는 ~/.zshrc에 추가

# Python 3.11 경로를 PATH 맨 앞에
export PATH="/usr/local/opt/python@3.11/bin:$PATH"

# 적용
source ~/.bashrc  # 또는 source ~/.zshrc

# 확인
python3 --version  # Python 3.11.x 출력되어야 함
```

---

## 3. 매퍼 파일 사전 점검

### 목적
- **OGNL 표현식**: MyBatis에서 복잡한 표현식 (예: `@java.lang.Math@max(...)`)
- **${} 변수**: 동적 SQL 변수 (예: `SELECT * FROM ${tableName}`)

### check_mappers.py

```python
#!/usr/bin/env python3
"""
매퍼 파일 사전 점검

OGNL 표현식 및 ${} 변수 검색
"""

import os
import re
import json
from pathlib import Path
from typing import List, Dict, Any
from lxml import etree


def find_mapper_files(workspace: str) -> List[str]:
    """
    매퍼 XML 파일 찾기

    Args:
        workspace: 소스 워크스페이스 경로

    Returns:
        매퍼 파일 경로 리스트
    """
    mapper_files = []
    for root, dirs, files in os.walk(workspace):
        for file in files:
            if file.endswith('Mapper.xml') or file.endswith('mapper.xml'):
                mapper_files.append(os.path.join(root, file))
    return mapper_files


def check_ognl_expressions(xml_content: str) -> List[Dict[str, Any]]:
    """
    OGNL 표현식 검색

    패턴:
    - @package.Class@method(...)
    - @package.Class@CONSTANT
    - new ClassName(...)

    Args:
        xml_content: XML 내용

    Returns:
        OGNL 표현식 리스트
    """
    ognl_patterns = [
        r'@[\w\.]+@\w+\(',  # @Class@method(
        r'@[\w\.]+@\w+',     # @Class@CONSTANT
        r'new\s+[\w\.]+\(',  # new Class(
    ]

    findings = []
    for pattern in ognl_patterns:
        matches = re.finditer(pattern, xml_content)
        for match in matches:
            # 줄 번호 찾기
            line_num = xml_content[:match.start()].count('\n') + 1

            # 전후 컨텍스트 추출 (50자)
            start = max(0, match.start() - 50)
            end = min(len(xml_content), match.end() + 50)
            context = xml_content[start:end].strip()

            findings.append({
                'type': 'OGNL',
                'pattern': match.group(0),
                'line': line_num,
                'context': context
            })

    return findings


def check_dollar_variables(xml_content: str) -> List[Dict[str, Any]]:
    """
    ${} 변수 검색

    Args:
        xml_content: XML 내용

    Returns:
        ${} 변수 리스트
    """
    # ${변수명} 패턴
    pattern = r'\$\{[\w\.]+\}'

    findings = []
    matches = re.finditer(pattern, xml_content)
    for match in matches:
        # 줄 번호
        line_num = xml_content[:match.start()].count('\n') + 1

        # 전후 컨텍스트
        start = max(0, match.start() - 50)
        end = min(len(xml_content), match.end() + 50)
        context = xml_content[start:end].strip()

        # 변수명 추출
        var_name = match.group(0)[2:-1]  # ${ 제거, } 제거

        findings.append({
            'type': 'DOLLAR_VAR',
            'variable': var_name,
            'pattern': match.group(0),
            'line': line_num,
            'context': context
        })

    return findings


def check_mapper_file(file_path: str) -> Dict[str, Any]:
    """
    단일 매퍼 파일 점검

    Args:
        file_path: 매퍼 파일 경로

    Returns:
        점검 결과
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        xml_content = f.read()

    ognl_findings = check_ognl_expressions(xml_content)
    dollar_findings = check_dollar_variables(xml_content)

    return {
        'file': file_path,
        'ognl_count': len(ognl_findings),
        'dollar_var_count': len(dollar_findings),
        'ognl_expressions': ognl_findings,
        'dollar_variables': dollar_findings
    }


def main():
    """메인 실행"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python check_mappers.py <workspace_path>")
        sys.exit(1)

    workspace = sys.argv[1]

    print("=" * 60)
    print("OMA Mapper Pre-Check")
    print("=" * 60)
    print("")

    # 매퍼 파일 찾기
    print(f"Scanning workspace: {workspace}")
    mapper_files = find_mapper_files(workspace)
    print(f"Found {len(mapper_files)} mapper files")
    print("")

    # 점검 실행
    results = []
    total_ognl = 0
    total_dollar = 0

    for mapper_file in mapper_files:
        result = check_mapper_file(mapper_file)
        results.append(result)

        total_ognl += result['ognl_count']
        total_dollar += result['dollar_var_count']

    # 요약 출력
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total Mappers: {len(mapper_files)}")
    print(f"OGNL Expressions: {total_ognl}")
    print(f"${} Variables: {total_dollar}")
    print("")

    # 상세 출력
    if total_ognl > 0:
        print("=" * 60)
        print("OGNL Expressions Found")
        print("=" * 60)
        for result in results:
            if result['ognl_count'] > 0:
                print(f"\n{result['file']}:")
                for finding in result['ognl_expressions']:
                    print(f"  Line {finding['line']}: {finding['pattern']}")
                    print(f"    Context: {finding['context'][:100]}...")
        print("")

    if total_dollar > 0:
        print("=" * 60)
        print("${} Variables Found")
        print("=" * 60)
        for result in results:
            if result['dollar_var_count'] > 0:
                print(f"\n{result['file']}:")
                for finding in result['dollar_variables']:
                    print(f"  Line {finding['line']}: ${{{finding['variable']}}}")
                    print(f"    Context: {finding['context'][:100]}...")
        print("")

    # JSON 리포트 저장
    report_file = 'mapper-precheck-report.json'
    with open(report_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_mappers': len(mapper_files),
                'total_ognl_expressions': total_ognl,
                'total_dollar_variables': total_dollar
            },
            'details': results
        }, f, indent=2, ensure_ascii=False)

    print(f"Detailed report saved: {report_file}")
    print("")

    # 경고 출력
    if total_ognl > 0:
        print("⚠️  WARNING: OGNL expressions detected!")
        print("   OGNL expressions may not work correctly after conversion.")
        print("   Manual review required.")
        print("")

    if total_dollar > 0:
        print("⚠️  WARNING: ${} variables detected!")
        print("   Dynamic table/column names require special handling.")
        print("   Ensure test cases include these variables.")
        print("")

    # 종료 코드
    if total_ognl > 0 or total_dollar > 0:
        print("=" * 60)
        print("Action Required:")
        print("  1. Review mapper-precheck-report.json")
        print("  2. For OGNL: Consider refactoring or manual conversion")
        print("  3. For ${}: Ensure TC parameters include these values")
        print("=" * 60)

    print("")
    print("✓ Pre-check complete")


if __name__ == '__main__':
    main()
```

### 실행
```bash
chmod +x check_mappers.py
python3 check_mappers.py /path/to/source/workspace
```

---

## 4. 통합 체크 스크립트

### run_all_checks.sh

```bash
#!/bin/bash

echo "========================================="
echo "OMA Complete Environment Check"
echo "========================================="
echo ""

# 1. 환경 점검
echo "[Step 1/2] Checking environment..."
./check_environment.sh
ENV_EXIT=$?

if [ $ENV_EXIT -ne 0 ]; then
    echo ""
    echo "✗ Environment check failed"
    echo "Fix environment issues before proceeding"
    exit 1
fi

echo ""
echo "✓ Environment check passed"
echo ""

# 2. 매퍼 사전 점검
if [ -z "$1" ]; then
    echo "⚠ Skipping mapper pre-check (no workspace path provided)"
    echo ""
    echo "To check mappers:"
    echo "  ./run_all_checks.sh /path/to/source/workspace"
else
    echo "[Step 2/2] Checking mapper files..."
    python3 check_mappers.py "$1"
    MAPPER_EXIT=$?
    
    if [ $MAPPER_EXIT -ne 0 ]; then
        echo ""
        echo "⚠ Mapper check found issues (see above)"
    fi
fi

echo ""
echo "========================================="
echo "✓ All checks complete"
echo "========================================="
```

### 실행
```bash
chmod +x run_all_checks.sh

# 환경만 체크
./run_all_checks.sh

# 환경 + 매퍼 체크
./run_all_checks.sh /path/to/source/workspace
```

---

## 5. 체크리스트

### 구현 시작 전
- [ ] Python 3.11 설치
- [ ] python3 → Python 3.11 링크 설정
- [ ] Java 11+ 설치
- [ ] Maven 설치
- [ ] AWS CLI 설치 및 설정
- [ ] PostgreSQL client 설치 (선택)
- [ ] `pip install -r requirements.txt`

### OMA 실행 전
- [ ] `./check_environment.sh` 실행 → 모두 ✓
- [ ] `python3 check_mappers.py <workspace>` 실행
- [ ] OGNL 표현식 확인 및 대응 계획
- [ ] ${} 변수 확인 및 TC에 포함

### 매퍼 점검 결과 대응

**OGNL 표현식 발견 시**:
- 수동 검토 필요
- 가능하면 리팩토링 (Java 코드로 이동)
- 또는 수동 변환

**${} 변수 발견 시**:
- TC 생성 시 해당 변수 포함
- 검증 시 파라미터에 값 제공
- 예: `${tableName}` → TC에 `"tableName": "users"` 추가

---

## 6. 문제 해결

### Python 3.11이 python3로 실행 안 됨

**원인**: 다른 버전이 우선순위에 있음

**해결**:
```bash
# 1. 현재 python3 확인
which python3
python3 --version

# 2. Python 3.11 위치 확인
which python3.11

# 3. 심볼릭 링크 재설정
sudo rm /usr/local/bin/python3
sudo ln -s $(which python3.11) /usr/local/bin/python3

# 4. 확인
python3 --version  # Python 3.11.x
```

### Java 버전이 여러 개

**해결**:
```bash
# macOS
export JAVA_HOME=$(/usr/libexec/java_home -v 11)

# Linux
export JAVA_HOME=/usr/lib/jvm/java-11-openjdk

# 확인
java -version
```

### AWS CLI 설정 안 됨

**해결**:
```bash
aws configure

# 입력:
# AWS Access Key ID: [your-key]
# AWS Secret Access Key: [your-secret]
# Default region name: ap-northeast-2
# Default output format: json
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-27
- 목적: 환경 구성 및 사전 점검
