-- =============================================================================
-- 08_create_otp_codes.sql
-- =============================================================================
-- OTP (one-time password) codes for email-based login.
--
-- Run this AFTER 02_create_customers.sql (no FK dependency, but it's
-- conceptually part of the customer-auth story). Safe to run on an
-- existing database — CREATE TABLE IF NOT EXISTS.
--
-- Design notes
-- ------------
-- - No FK to customers: an OTP can be requested for an email that doesn't
--   have a customer record yet (the account is auto-created on first
--   successful verification — see services/auth_service.py).
-- - Only the SHA-256 hash of the 6-digit code is stored, never the
--   plaintext code.
-- - attempt_count / max_attempts implements a simple brute-force guard:
--   once attempt_count reaches max_attempts, that OTP row can no longer
--   be used to verify, even if it hasn't expired yet.
-- - Old rows are never deleted by the application. For a production
--   system you'd add a cleanup job (DELETE WHERE expires_at < NOW() -
--   INTERVAL 7 DAY); out of scope for this learning project.
-- =============================================================================

CREATE TABLE IF NOT EXISTS otp_codes (
    otp_id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    email          VARCHAR(254)     NOT NULL,
    code_hash      CHAR(64)         NOT NULL
        COMMENT 'SHA-256 hex digest of the 6-digit code — plaintext is never stored',
    purpose        ENUM('login')    NOT NULL DEFAULT 'login',
    attempt_count  TINYINT UNSIGNED NOT NULL DEFAULT 0,
    max_attempts   TINYINT UNSIGNED NOT NULL DEFAULT 5,
    expires_at     DATETIME         NOT NULL,
    consumed_at    DATETIME         NULL,
    created_at     DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_otp_attempts CHECK (attempt_count <= max_attempts),

    -- Covers both lookups auth_service needs: "most recent OTP for this
    -- email" (cooldown check) and "most recent active OTP" (verification).
    INDEX idx_otp_email_created (email, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
