# Prioritised backlog

Ordered by MoSCoW, then WSJF (cost of delay / story points), with dependencies pulled ahead.

| # | ID | MoSCoW | Story | Pts | WSJF | Depends on |
|---|---|---|---|---|---|---|
| 1 | FNOL-04 | Must | As a claims handler, I want digital claims created in the core claims system automatically, so that I never re-key data. | 13 | 1.92 | - |
| 2 | FNOL-01 | Must | As a policyholder who has just had an accident, I want to report my claim in the app in under 10 minutes, so that I don't have to wait on hold to start my claim. | 8 | 2.88 | FNOL-04 |
| 3 | FNOL-02 | Must | As a policyholder, I want to upload photos of the damage during notification, so that my claim can be assessed without an inspection visit. | 5 | 4.2 | FNOL-01 |
| 4 | FNOL-12 | Must | As a data protection officer, I want claim photos and personal data retained per policy, so that we comply with UK GDPR. | 3 | 7.67 | FNOL-02 |
| 5 | FNOL-10 | Must | As a claims director, I want a weekly dashboard of digital take-up, cycle time and hire days, so that I can track benefits against the business case. | 3 | 6.67 | FNOL-04 |
| 6 | FNOL-07 | Must | As a customer with a disability, I want the claim journey to meet WCAG 2.2 AA, so that I can report a claim independently. | 5 | 4.2 | FNOL-01 |
| 7 | FNOL-03 | Must | As a claims operations manager, I want simple claims routed straight to an approved repairer, so that cycle time and hire-car days fall. | 8 | 2.5 | FNOL-01 |
| 8 | FNOL-11 | Should | As a policyholder, I want to save a part-completed claim and return later, so that I can finish when I'm somewhere safe. | 3 | 3.33 | FNOL-01 |
| 9 | FNOL-06 | Should | As a policyholder, I want status updates by SMS and in the app, so that I don't have to chase my claim. | 5 | 2.6 | FNOL-04 |
| 10 | FNOL-05 | Should | As a counter-fraud analyst, I want fraud indicators scored at notification, so that suspicious claims are referred before payment. | 8 | 2.5 | FNOL-02 |
| 11 | FNOL-08 | Could | As a broker, I want to notify claims for my clients through a portal, so that broker claims also benefit from faster cycle times. | 8 | 1.12 | FNOL-04 |
| 12 | FNOL-09 | Won't | As a claims handler, I want AI damage estimates from photos, so that reserves are set accurately on day one. | 13 | 0.77 | FNOL-02 |

**Effort by priority:** Must 45 pts, Should 16 pts, Could 8 pts, Won't 13 pts

## Validation

- WARNING: Musts are 65% of in-scope effort; DSDM guidance is at most 60% so Shoulds/Coulds act as contingency

## Acceptance criteria

### FNOL-04: digital claims created in the core claims system automatically

```gherkin
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
```

### FNOL-01: to report my claim in the app in under 10 minutes

```gherkin
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
```

### FNOL-02: to upload photos of the damage during notification

```gherkin
Feature: To upload photos of the damage during notification
  As a policyholder, I want to upload photos of the damage during notification, so that my claim can be assessed without an inspection visit.
  Scenario: Valid photos uploaded
    Given I am on the damage step
    When I upload between 2 and 12 JPEG or HEIC photos under 15 MB each
    Then thumbnails are shown
    And photos are stored against the claim with EXIF timestamp and location

  Scenario: Photo too large
    Given I am on the damage step
    When I upload a 40 MB file
    Then I see 'Photos must be under 15 MB'
    And the file is not stored
```

### FNOL-12: claim photos and personal data retained per policy

```gherkin
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
```

### FNOL-10: a weekly dashboard of digital take-up, cycle time and hire days

```gherkin
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
```

### FNOL-07: the claim journey to meet WCAG 2.2 AA

```gherkin
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
```

### FNOL-03: simple claims routed straight to an approved repairer

```gherkin
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
```

### FNOL-11: to save a part-completed claim and return later

```gherkin
Feature: To save a part-completed claim and return later
  As a policyholder, I want to save a part-completed claim and return later, so that I can finish when I'm somewhere safe.
  Scenario: Resume a draft
    Given I saved a draft claim less than 7 days ago
    When I reopen the app
    Then I am taken back to the step I left
```

### FNOL-06: status updates by SMS and in the app

```gherkin
Feature: Status updates by SMS and in the app
  As a policyholder, I want status updates by SMS and in the app, so that I don't have to chase my claim.
  Scenario: Repairer booked
    Given my claim has been routed to a repairer
    When the repairer accepts the job
    Then I receive an SMS with the repairer name and booking date
```

### FNOL-05: fraud indicators scored at notification

```gherkin
Feature: Fraud indicators scored at notification
  As a counter-fraud analyst, I want fraud indicators scored at notification, so that suspicious claims are referred before payment.
  Scenario: High-risk claim referred
    Given the photo EXIF date is more than 7 days before the stated incident date
    When the claim is scored
    Then the claim is flagged for counter-fraud review
    And straight-through routing is blocked
```

### FNOL-08: to notify claims for my clients through a portal

```gherkin
Feature: To notify claims for my clients through a portal
  As a broker, I want to notify claims for my clients through a portal, so that broker claims also benefit from faster cycle times.
  Scenario: Broker notifies a claim
    Given I am an authorised broker user
    When I submit a claim for a client
    Then the policyholder is notified by email
    And the claim is linked to my agency code
```

### FNOL-09: AI damage estimates from photos

```gherkin
Feature: AI damage estimates from photos
  As a claims handler, I want AI damage estimates from photos, so that reserves are set accurately on day one.
  Scenario: Deferred to phase 2
    Given phase 1 is live
    When photo volumes exceed 20,000
    Then a vendor evaluation is started
```
