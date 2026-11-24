-- Third normal form. Money is whole pence, and times are UTC.
CREATE TABLE pipeline_run (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(30) NOT NULL,
  status ENUM('running','succeeded','partial','failed') NOT NULL DEFAULT 'running',
  started_at DATETIME(3) NOT NULL DEFAULT (UTC_TIMESTAMP(3)),
  finished_at DATETIME(3) NULL,
  pages INT UNSIGNED NOT NULL DEFAULT 0,
  failed_pages INT UNSIGNED NOT NULL DEFAULT 0,
  retries INT UNSIGNED NOT NULL DEFAULT 0,
  loaded INT UNSIGNED NOT NULL DEFAULT 0,
  rejected INT UNSIGNED NOT NULL DEFAULT 0,
  duplicates INT UNSIGNED NOT NULL DEFAULT 0,
  message VARCHAR(500) NULL,
  KEY ix_run_source_started (source, started_at)
) ENGINE=InnoDB;

CREATE TABLE rejected_record (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  run_id INT UNSIGNED NOT NULL,
  reason VARCHAR(500) NOT NULL,
  raw JSON NOT NULL,
  KEY ix_rejected_run (run_id),
  CONSTRAINT fk_rejected_run FOREIGN KEY (run_id) REFERENCES pipeline_run (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE category (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  UNIQUE KEY uq_category_name (name)
) ENGINE=InnoDB;

CREATE TABLE book (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  external_id VARCHAR(255) NOT NULL,
  title VARCHAR(300) NOT NULL,
  url VARCHAR(500) NOT NULL,
  category_id INT UNSIGNED NOT NULL,
  rating TINYINT UNSIGNED NOT NULL,
  first_seen_run INT UNSIGNED NOT NULL,
  last_seen_run INT UNSIGNED NOT NULL,
  UNIQUE KEY uq_book_external (external_id),
  KEY ix_book_category_rating (category_id, rating),
  CONSTRAINT ck_book_rating CHECK (rating BETWEEN 1 AND 5),
  CONSTRAINT fk_book_category FOREIGN KEY (category_id) REFERENCES category (id),
  CONSTRAINT fk_book_first_run FOREIGN KEY (first_seen_run) REFERENCES pipeline_run (id),
  CONSTRAINT fk_book_last_run FOREIGN KEY (last_seen_run) REFERENCES pipeline_run (id)
) ENGINE=InnoDB;

-- One row per book per day, so re-running on the same day corrects it instead of duplicating.
CREATE TABLE book_price (
  book_id INT UNSIGNED NOT NULL,
  observed_on DATE NOT NULL,
  price_pence INT UNSIGNED NOT NULL,
  in_stock BOOLEAN NOT NULL,
  PRIMARY KEY (book_id, observed_on),
  KEY ix_price_day (observed_on, price_pence),
  CONSTRAINT ck_price_positive CHECK (price_pence > 0),
  CONSTRAINT fk_price_book FOREIGN KEY (book_id) REFERENCES book (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE author (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(150) NOT NULL,
  UNIQUE KEY uq_author_name (name)
) ENGINE=InnoDB;

CREATE TABLE quote (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  digest CHAR(64) CHARACTER SET ascii NOT NULL,
  text TEXT NOT NULL,
  author_id INT UNSIGNED NOT NULL,
  last_seen_run INT UNSIGNED NOT NULL,
  UNIQUE KEY uq_quote_digest (digest),
  KEY ix_quote_author (author_id),
  CONSTRAINT fk_quote_author FOREIGN KEY (author_id) REFERENCES author (id),
  CONSTRAINT fk_quote_run FOREIGN KEY (last_seen_run) REFERENCES pipeline_run (id)
) ENGINE=InnoDB;

CREATE TABLE tag (
  id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(60) NOT NULL,
  UNIQUE KEY uq_tag_name (name)
) ENGINE=InnoDB;

CREATE TABLE quote_tag (
  quote_id INT UNSIGNED NOT NULL,
  tag_id INT UNSIGNED NOT NULL,
  PRIMARY KEY (quote_id, tag_id),
  KEY ix_quote_tag_tag (tag_id, quote_id),
  CONSTRAINT fk_qt_quote FOREIGN KEY (quote_id) REFERENCES quote (id) ON DELETE CASCADE,
  CONSTRAINT fk_qt_tag FOREIGN KEY (tag_id) REFERENCES tag (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE VIEW current_book AS
SELECT b.id, b.title, c.name AS category, b.rating, p.price_pence / 100 AS price_gbp,
       p.in_stock, p.observed_on
FROM book b
JOIN category c ON c.id = b.category_id
JOIN book_price p ON p.book_id = b.id
 AND p.observed_on = (SELECT MAX(x.observed_on) FROM book_price x WHERE x.book_id = b.id);
