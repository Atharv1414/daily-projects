Feature: Claim photos and personal data retained per policy
  As a data protection officer, I want claim photos and personal data retained per policy, so that we comply with UK GDPR.
  Scenario: Retention applied
    Given a claim closed more than 6 years ago
    When the retention job runs
    Then photos and personal data are deleted
    And the deletion is logged for audit

  Scenario: Claim under litigation hold
    Given a closed claim more than 6 years old is flagged for litigation hold
    When the retention job runs
    Then its data is kept
    And the hold reason is logged
