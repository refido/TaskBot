-- DB1 paper example. All inputs are fictional. Reads no application tables.
WITH customers(label, area, last_outcome, updated_day) AS (
    VALUES ('A', 'inside', 'out of stock', 0),
           ('B', 'inside', 'registration limit', 0),
           ('C', 'inside', 'new', 0),
           ('D', 'inside', 'maximum yesterday', 0),
           ('E', 'inside', 'older success', -2),
           ('F', 'inside', 'untouched by last run', -2),
           ('G', 'outside', 'older success', -3)
), scenarios(scenario, month_start, area, finished_today) AS (
    VALUES ('ordinary', 0, 'inside', ''),
           ('month start', 1, 'inside', ''),
           ('restart after C', 1, 'inside', 'C'),
           ('outside eligible', 0, 'outside', '')
)
SELECT scenario, label
FROM scenarios
JOIN customers ON customers.area = scenarios.area
WHERE label <> finished_today
  AND (last_outcome <> 'maximum yesterday' OR month_start = 1)
ORDER BY scenario,
         CASE
             WHEN last_outcome = 'new' THEN 0
             WHEN last_outcome = 'out of stock' THEN 1
             WHEN last_outcome = 'registration limit' THEN 2
             WHEN last_outcome = 'maximum yesterday' THEN 3
             ELSE 4
         END,
         updated_day, label;
