SELECT
{{DIM_SELECT}}
      COUNT(DISTINCT CASE
          WHEN t.source = 'efs' THEN t.transaction_id
      END) AS efs_txns,
      COUNT(DISTINCT CASE
          WHEN t.source <> 'efs'
           AND UPPER(s.sub_service_name) IN ({{CORE_SUBSERVICE_PLACEHOLDERS}})
          THEN t.transaction_id
      END) AS non_efs_txns,
      COUNT(DISTINCT CASE
          WHEN t.source = 'efs'
            OR UPPER(s.sub_service_name) IN ({{CORE_SUBSERVICE_PLACEHOLDERS}})
          THEN t.transaction_id
      END) AS core_txns,
      COUNT(DISTINCT t.transaction_id) AS all_txns,
      SUM(t.revenue_amount) AS revenue
FROM [datamart].[fact_transaction] t
LEFT JOIN [datamart].[dim_service] s
       ON s.service_key = t.service_key
JOIN [datamart].[dim_entity] e
     ON e.entity_key = t.entity_key
LEFT JOIN [datamart].[dim_customer] c
       ON c.customer_key = t.customer_key
LEFT JOIN [datamart].[dim_parent_customer] pc
       ON pc.parent_customer_key = t.parent_customer_key
WHERE t.transaction_date >= ?
  AND t.transaction_date < ?
{{FILTERS}}
GROUP BY
      {{DIM_GROUP}}
ORDER BY {{ORDER_BY}};
