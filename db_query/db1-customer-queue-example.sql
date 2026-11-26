-- DB1 paper example for one operator. All labels and WIB dates are fictional.
WITH customers(label, area, outcome, updated_on, last_sale_on) AS (
    VALUES ('A', 'inside', 'out of stock',       '2026-10-30', NULL),
           ('B', 'inside', 'registration limit', '2026-10-30', NULL),
           ('C', 'inside', '',                   '2026-10-30', NULL),
           ('D', 'inside', 'maximum quota',      '2026-10-30', NULL),
           ('F', 'inside', 'ordinary',           '2026-10-28', NULL),
           ('E', 'inside', 'completed',          '2026-10-28', '2026-10-28'),
           ('G', 'outside', 'completed',         '2026-10-27', '2026-10-27')
), scenarios(scenario, business_day, month_start, first_processing_day, area, finished_today) AS (
    VALUES ('same day',             '2026-10-30', '2026-10-01', 0, 'inside',  ''),
           ('ordinary',             '2026-10-31', '2026-10-01', 0, 'inside',  ''),
           ('month start',          '2026-11-02', '2026-11-01', 1, 'inside',  ''),
           ('later in the month',   '2026-11-03', '2026-11-01', 0, 'inside',  ''),
           ('restart after C',      '2026-11-02', '2026-11-01', 1, 'inside',  'C'),
           ('outside eligible',     '2026-10-31', '2026-10-01', 0, 'outside', '')
)
SELECT scenario, label
FROM scenarios
JOIN customers ON customers.area = scenarios.area
WHERE label <> finished_today
  AND (outcome <> 'maximum quota' OR updated_on < month_start)
  AND (outcome NOT IN ('out of stock', 'registration limit') OR updated_on < business_day)
ORDER BY scenario,
         CASE
             WHEN outcome = '' AND last_sale_on IS NULL THEN 0
             WHEN outcome = 'out of stock' THEN 1
             WHEN outcome = 'registration limit' THEN 2
             WHEN outcome = 'maximum quota' AND first_processing_day = 1 THEN 3
             ELSE 4
         END,
         updated_on, label;
