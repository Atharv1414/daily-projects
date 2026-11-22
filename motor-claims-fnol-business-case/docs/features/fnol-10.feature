Feature: A weekly dashboard of digital take-up, cycle time and hire days
  As a claims director, I want a weekly dashboard of digital take-up, cycle time and hire days, so that I can track benefits against the business case.
  Scenario: Weekly benefits report
    Given it is Monday 08:00
    When the reporting job runs
    Then take-up, mean cycle days and hire days are reported by region
    And variance against business-case targets is shown

  Scenario: Source data late
    Given the claims system extract has not arrived by 07:00
    When the reporting job runs
    Then the report is published with a 'data incomplete' banner
    And the MI team is alerted
