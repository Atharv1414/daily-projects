-- Price and rating by category
SELECT category, COUNT(*) AS books, ROUND(AVG(price_gbp), 2) AS avg_price,
       ROUND(AVG(rating), 2) AS avg_rating
FROM current_book GROUP BY category HAVING books >= 10 ORDER BY avg_price DESC LIMIT 10;

-- Biggest price moves between consecutive observations
SELECT b.title, m.observed_on, m.previous / 100 AS was, m.price_pence / 100 AS now
FROM (SELECT book_id, observed_on, price_pence,
             LAG(price_pence) OVER (PARTITION BY book_id ORDER BY observed_on) AS previous
      FROM book_price) m
JOIN book b ON b.id = m.book_id
WHERE m.previous IS NOT NULL AND m.previous <> m.price_pence
ORDER BY ABS(CAST(m.price_pence AS SIGNED) - CAST(m.previous AS SIGNED)) DESC LIMIT 10;

-- Pipeline health
SELECT source, status, COUNT(*) AS runs, SUM(rejected) AS rejected, SUM(retries) AS retries
FROM pipeline_run GROUP BY source, status;
