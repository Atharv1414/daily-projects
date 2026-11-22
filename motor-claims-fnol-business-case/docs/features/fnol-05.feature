Feature: Fraud indicators scored at notification
  As a counter-fraud analyst, I want fraud indicators scored at notification, so that suspicious claims are referred before payment.
  Scenario: High-risk claim referred
    Given the photo EXIF date is more than 7 days before the stated incident date
    When the claim is scored
    Then the claim is flagged for counter-fraud review
    And straight-through routing is blocked
