Feature: Digital claims created in the core claims system automatically
  As a claims handler, I want digital claims created in the core claims system automatically, so that I never re-key data.
  Scenario: Claim created via API
    Given the claims system API is available
    When a digital claim is submitted
    Then a claim record is created with all FNOL fields mapped
    And the API call is retried up to 3 times on failure

  Scenario: Claims system unavailable
    Given the claims system API returns errors for 10 minutes
    When a digital claim is submitted
    Then the claim is queued and the customer still receives a reference
    And an alert is raised to IT support
