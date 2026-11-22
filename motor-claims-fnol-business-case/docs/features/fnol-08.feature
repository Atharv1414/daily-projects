Feature: To notify claims for my clients through a portal
  As a broker, I want to notify claims for my clients through a portal, so that broker claims also benefit from faster cycle times.
  Scenario: Broker notifies a claim
    Given I am an authorised broker user
    When I submit a claim for a client
    Then the policyholder is notified by email
    And the claim is linked to my agency code
