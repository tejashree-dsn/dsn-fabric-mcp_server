SELECT
      t.transaction_key AS transaction_key,
      t.transaction_id AS transaction_id,
      t.source AS source,
      t.transaction_date AS transaction_date,
      e.entity_name AS entity_name,
      e.agency_code AS agency_code,
      c.customer_name AS customer_name,
      c.customer_license_number AS customer_license_number,
      pc.parent_customer_name AS parent_customer,
      s.service_name AS service_name,
      s.sub_service_name AS sub_service_name,
      v.vehicle_id AS vehicle_id,
      t.revenue_amount AS revenue_amount
FROM [datamart].[fact_transaction] t
LEFT JOIN [datamart].[dim_service] s
       ON s.service_key = t.service_key
LEFT JOIN [datamart].[dim_vehicle] v
       ON v.vehicle_key = t.vehicle_key
JOIN [datamart].[dim_entity] e
     ON e.entity_key = t.entity_key
LEFT JOIN [datamart].[dim_customer] c
       ON c.customer_key = t.customer_key
JOIN [datamart].[dim_parent_customer] pc
     ON pc.parent_customer_key = t.parent_customer_key
WHERE t.transaction_date >= ?
  AND t.transaction_date < ?
{{FILTERS}}
ORDER BY t.transaction_date, e.entity_name, t.transaction_key;
