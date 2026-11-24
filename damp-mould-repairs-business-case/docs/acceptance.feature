Feature: Damp and mould cases meet their statutory clocks

  Scenario: US01 every open case to show its statutory clocks and time remaining
    Given a significant hazard reported 8 working days ago with no completed investigation
    When I open the clock board
    Then the case is amber and shows 2 working days remaining

  Scenario: US02 jobs ordered by statutory deadline
    Given a routine repair raised on Monday and a make-safe job raised on Tuesday due in 5 days
    When a crew becomes free on Wednesday
    Then the make-safe job is offered first

  Scenario: US03 one summary queue, a standard template and a second trained administrator
    Given a surveyor has submitted findings and the action plan
    When either administrator opens the queue
    Then the oldest summary is offered first and the send is time-stamped

  Scenario: US04 emergencies dispatched to a crew as soon as they are triaged
    Given a report triaged as an emergency
    When triage is saved
    Then a make-safe job is created and the duty crew is alerted

  Scenario: US05 a case to be impossible to close without triage, summary and completion evidence
    Given a significant case with no written summary
    When someone tries to close it
    Then closure is refused and the missing step is named

  Scenario: US06 an unchangeable log of every milestone and who recorded it
    Given a milestone that was corrected
    When I view its history
    Then the old value, new value, person, time and reason are all shown

  Scenario: US07 to assess low-risk cases from photos and readings
    Given a non-emergency case with usable photos and no vulnerability or health flag
    When I complete a desk assessment
    Then the case moves to works without a visit and my reasons are recorded

  Scenario: US08 to choose and confirm a visit time by text or phone
    Given a survey is needed
    When I receive the booking message
    Then I can pick a slot, and I get a reminder 24 hours before

  Scenario: US09 post inspections selected by risk
    Given a routine first-visit repair with photos accepted
    When it is completed
    Then it is inspected only if sampled

  Scenario: US10 a failed visit to release a new slot within 2 working days
    Given a visit recorded as no access
    When the surveyor leaves
    Then the tenant is offered slots within 2 working days

  Scenario: US11 common damp parts forecast and stocked
    Given three extractor fans used per day on average
    When stock falls below five days of cover
    Then an order is raised

  Scenario: US12 to see where my case is
    Given an open case
    When I follow my link or call
    Then I see the current step and the next date

