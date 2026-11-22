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
