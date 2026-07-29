package com.oma.validator.model;

/**
 * TC 하나에 대한 검증 결과 (소스/타겟 실행 결과 묶음)
 *
 * 실제 결과 비교(행수/값)는 Python comparator가 수행하므로, 여기서는 소스/타겟
 * ExecutionResult를 담아 전달만 한다. 추출/실행 중 예외 시 error로 표시한다.
 *
 * 변경 이력:
 * 2026-07-27 | OMA Team | 초기 생성
 */
public class ValidationResult {

    private final String tcId;
    private final String status;   // "ok" | "error"
    private final ExecutionResult sourceResult;
    private final ExecutionResult targetResult;
    private final String errorMessage;

    private ValidationResult(String tcId, String status,
                             ExecutionResult sourceResult,
                             ExecutionResult targetResult,
                             String errorMessage) {
        this.tcId = tcId;
        this.status = status;
        this.sourceResult = sourceResult;
        this.targetResult = targetResult;
        this.errorMessage = errorMessage;
    }

    public static ValidationResult of(String tcId, ExecutionResult source,
                                      ExecutionResult target) {
        return new ValidationResult(tcId, "ok", source, target, null);
    }

    public static ValidationResult error(String tcId, String message) {
        return new ValidationResult(tcId, "error", null, null, message);
    }

    public String getTcId() {
        return tcId;
    }

    public String getStatus() {
        return status;
    }
}
