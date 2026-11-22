Feature: The claim journey to meet WCAG 2.2 AA
  As a customer with a disability, I want the claim journey to meet WCAG 2.2 AA, so that I can report a claim independently.
  Scenario: Screen reader journey
    Given I use VoiceOver
    When I complete the claim journey
    Then every control has an accessible name
    And no step requires a mouse

  Scenario: Vulnerability declared
    Given I indicate I need extra support
    When I submit the claim
    Then the claim is routed to the vulnerable customer team
    And straight-through processing is disabled
