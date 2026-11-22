Feature: Simple claims routed straight to an approved repairer
  As a claims operations manager, I want simple claims routed straight to an approved repairer, so that cycle time and hire-car days fall.
  Scenario: Simple claim routed automatically
    Given a single-vehicle claim with no injury and no third party
    And estimated damage under £3,000
    When the claim is submitted
    Then it is assigned to the nearest approved repairer within 1 hour
    And no handler call is created

  Scenario: Injury reported
    Given the customer ticks 'someone was injured'
    When the claim is submitted
    Then the claim goes to the injury team queue
    And a handler call is scheduled within 4 working hours

  Scenario: Claim above the straight-through value cap
    Given estimated damage is £3,000 or more
    When the claim is submitted
    Then the claim goes to a handler for review
    And the customer is told a handler will call within 1 working day
