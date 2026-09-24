import unittest
from datetime import date

from models import CoreGrain, QueryRequest, ReportType
from query_builder import QueryBuildError, build_query_plan, resolve_window


class QueryBuilderTests(unittest.TestCase):
    def assert_params_match(self, plan):
        for dataset in plan.datasets:
            self.assertEqual(
                dataset.sql.count("?"),
                len(dataset.params),
                f"placeholder mismatch in {dataset.name}",
            )

    def test_month_window_is_exclusive(self):
        req = QueryRequest(report=ReportType.CORE_TRANSACTIONS, year=2026, month=6)
        start, upper = resolve_window(req)
        self.assertEqual(start, date(2026, 6, 1))
        self.assertEqual(upper, date(2026, 7, 1))

    def test_december_rolls_year(self):
        req = QueryRequest(report=ReportType.CORE_TRANSACTIONS, year=2026, month=12)
        start, upper = resolve_window(req)
        self.assertEqual(start, date(2026, 12, 1))
        self.assertEqual(upper, date(2027, 1, 1))

    def test_explicit_window(self):
        req = QueryRequest(
            report=ReportType.CORE_TRANSACTIONS,
            from_date="2026-04-01",
            to_date="2026-07-01",
        )
        start, upper = resolve_window(req)
        self.assertEqual(start, date(2026, 4, 1))
        self.assertEqual(upper, date(2026, 7, 1))

    def test_non_contiguous_months_rejected(self):
        with self.assertRaises(ValueError):
            QueryRequest(report=ReportType.CORE_TRANSACTIONS, year=2026, months=[1, 3])

    def test_core_query_parameter_order_and_count(self):
        req = QueryRequest(
            report=ReportType.CORE_TRANSACTIONS,
            year=2026,
            month=6,
            agency_codes=["fata", "fota"],
            parent_customer="Morgan Auto Group",
            grain=CoreGrain.MONTH_AGENCY,
        )
        plan = build_query_plan(req)
        self.assert_params_match(plan)
        params = plan.datasets[0].params
        # 4 sub-services x 2 CASE expressions, then from/to, agencies, parent.
        self.assertEqual(len(params), 8 + 2 + 2 + 1)
        self.assertEqual(params[8], date(2026, 6, 1))
        self.assertEqual(params[9], date(2026, 7, 1))
        self.assertEqual(params[10:12], ("FATA", "FOTA"))
        self.assertEqual(params[12], "Morgan Auto Group")
        self.assertIn("COUNT(DISTINCT", plan.datasets[0].sql)
        self.assertIn("UPPER(s.sub_service_name)", plan.datasets[0].sql)

    def test_all_plans_have_matching_parameters(self):
        requests = [
            QueryRequest(report=ReportType.CORE_TRANSACTIONS, year=2026),
            QueryRequest(report=ReportType.PARENT_CUSTOMER_DETAIL, year=2026, parent_customer="Morgan Auto Group"),
            QueryRequest(report=ReportType.DEALER_SERVICE_SUMMARY, year=2026),
            QueryRequest(report=ReportType.AGGREGATE_SUMMARY, year=2026),
            QueryRequest(report=ReportType.REFERENCE_SUMMARY, year=2026, agency_codes=["FATA"]),
            QueryRequest(report=ReportType.EOMV_RETAIL, year=2026),
            QueryRequest(report=ReportType.MVD, year=2026, agency_codes=["FATA"]),
        ]
        for req in requests:
            with self.subTest(report=req.report):
                self.assert_params_match(build_query_plan(req))

    def test_parent_detail_requires_parent(self):
        req = QueryRequest(report=ReportType.PARENT_CUSTOMER_DETAIL, year=2026)
        with self.assertRaises(QueryBuildError):
            build_query_plan(req)

    def test_aggregate_rejects_agency_filter(self):
        req = QueryRequest(
            report=ReportType.AGGREGATE_SUMMARY,
            year=2026,
            agency_codes=["FATA"],
        )
        with self.assertRaises(QueryBuildError):
            build_query_plan(req)

    def test_reference_scope_is_case_normalized_in_sql(self):
        req = QueryRequest(report=ReportType.REFERENCE_SUMMARY, year=2026)
        plan = build_query_plan(req)
        self.assertIn("LOWER(LTRIM(RTRIM(t.source)))", plan.datasets[0].sql)
        self.assertIn("UPPER(LTRIM(RTRIM(e.entity_name)))", plan.datasets[0].sql)


if __name__ == "__main__":
    unittest.main()
