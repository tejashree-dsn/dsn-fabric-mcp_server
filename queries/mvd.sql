SELECT
      transaction_id,
      transaction_date,
      [system],
      agency_code,
      service_name,
      sub_service_name,
      quantity,
      price,
      revenue_amount,
      customers_id,
      customer_name,
      source
FROM [mvd].[transaction]
WHERE transaction_date >= ?
  AND transaction_date < ?
{{FILTERS}}
ORDER BY [system], transaction_date;
