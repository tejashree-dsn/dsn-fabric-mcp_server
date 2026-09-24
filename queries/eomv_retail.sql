SELECT
      t.transaction_id,
      t.source,
      t.transaction_date,
      e.entity_name,
      e.parent_entity_name,
      e.agency_code,
      s.service_name,
      s.sub_service_name,
      t.revenue_amount
FROM [datamart].[fact_transaction] t
JOIN [datamart].[dim_entity] e
     ON e.entity_key = t.entity_key
JOIN [datamart].[dim_service] s
     ON s.service_key = t.service_key
WHERE e.parent_entity_name = 'EOMV'
  AND s.service_name = 'Express Lane for DMV'
  AND t.transaction_date >= ?
  AND t.transaction_date < ?
ORDER BY t.transaction_date;
