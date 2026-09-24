SELECT
      e.entity_name,
      DATEFROMPARTS(YEAR(t.transaction_date), MONTH(t.transaction_date), 1) AS month_start,
      COUNT(DISTINCT t.transaction_id) AS transaction_count,
      SUM(t.revenue_amount) AS revenue_amount
FROM [datamart].[fact_transaction] t
JOIN [datamart].[dim_entity] e
     ON e.entity_key = t.entity_key
WHERE t.transaction_date >= ?
  AND t.transaction_date < ?
{{FILTERS}}
GROUP BY
      e.entity_name,
      DATEFROMPARTS(YEAR(t.transaction_date), MONTH(t.transaction_date), 1)
ORDER BY e.entity_name, month_start;
