SELECT
      c.parent_customer_name AS dealer,
      s.service_name AS service,
      DATEFROMPARTS(YEAR(t.transaction_date), MONTH(t.transaction_date), 1) AS month_start,
      COUNT(DISTINCT t.transaction_id) AS txns
FROM [datamart].[fact_transaction] t
JOIN [datamart].[dim_customer] c
     ON c.customer_key = t.customer_key
JOIN [datamart].[dim_service] s
     ON s.service_key = t.service_key
JOIN [datamart].[dim_entity] e
     ON e.entity_key = t.entity_key
WHERE t.transaction_date >= ?
  AND t.transaction_date < ?
{{FILTERS}}
GROUP BY
      c.parent_customer_name,
      s.service_name,
      DATEFROMPARTS(YEAR(t.transaction_date), MONTH(t.transaction_date), 1)
ORDER BY dealer, service, month_start;
