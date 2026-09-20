# FATF Guidance: Structuring (CTR Avoidance)

## Definition
Structuring, also called "structuring to evade reporting requirements," is the practice of breaking up
large financial transactions into smaller amounts — typically below the $10,000 Currency Transaction Report
(CTR) threshold — to avoid mandatory reporting by financial institutions.

## Regulatory Basis
- **31 U.S.C. § 5324** (US): Prohibits structuring or assisting in structuring any financial transaction
  to evade the reporting requirements of the Bank Secrecy Act (BSA).
- **FinCEN SAR Guidance (2021-01)**: Financial institutions must file a Suspicious Activity Report (SAR)
  when structuring is suspected, regardless of the dollar amount.
- **FATF Recommendation 20**: Countries should require financial institutions to report suspicious
  transactions related to structuring.

## Key Indicators
1. Multiple cash deposits or withdrawals from the same account within a short period (2–7 days),
   each just below $10,000 (commonly $9,000–$9,900).
2. Transactions split across multiple branches or ATMs on the same day.
3. Account holder appears nervous or asks specifically about reporting thresholds.
4. Sudden surge in transaction frequency without corresponding business justification.

## Detection Thresholds (Used by Rule Engine)
- **Amount window**: $8,000 – $9,999 per transaction (configurable)
- **Time window**: 3 calendar days (rolling)
- **Minimum transactions**: 3 within the window
- **Cumulative sum trigger**: > $10,000 in window = structuring flag

## SAR Filing Guidance
File a SAR with FinCEN when:
- The aggregate transaction amount is ≥ $5,000 AND
- The institution knows, suspects, or has reason to suspect structuring

Reference: FinCEN SAR Filing Instructions, Form 111 (Rev. 2019)
