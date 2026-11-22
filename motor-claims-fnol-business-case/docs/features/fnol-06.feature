Feature: Status updates by SMS and in the app
  As a policyholder, I want status updates by SMS and in the app, so that I don't have to chase my claim.
  Scenario: Repairer booked
    Given my claim has been routed to a repairer
    When the repairer accepts the job
    Then I receive an SMS with the repairer name and booking date
