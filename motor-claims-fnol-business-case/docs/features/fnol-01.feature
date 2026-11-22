Feature: To report my claim in the app in under 10 minutes
  As a policyholder who has just had an accident, I want to report my claim in the app in under 10 minutes, so that I don't have to wait on hold to start my claim.
  Scenario: Policyholder submits a complete claim
    Given I am logged in with an active motor policy
    And the incident date is within my policy period
    When I complete every mandatory step and press Submit
    Then a claim reference starting AMC- is shown
    And a confirmation email is sent within 5 minutes
    And the claim appears in the handler work queue

  Scenario: Incident outside the policy period
    Given my policy lapsed before the incident date
    When I enter the incident date
    Then I am told the policy was not active on that date
    And I am offered a call-back instead of continuing
