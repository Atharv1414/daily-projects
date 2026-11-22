Feature: To save a part-completed claim and return later
  As a policyholder, I want to save a part-completed claim and return later, so that I can finish when I'm somewhere safe.
  Scenario: Resume a draft
    Given I saved a draft claim less than 7 days ago
    When I reopen the app
    Then I am taken back to the step I left
