import unittest

from sql_validator import SQLValidationError, validate_select_only


class SQLValidatorTests(unittest.TestCase):
    def test_select_allowed(self):
        validate_select_only(
            "SELECT * FROM datamart.fact_transaction",
            allowed_schemas=["datamart"],
        )

    def test_cte_allowed(self):
        validate_select_only(
            "WITH x AS (SELECT 1 AS n) SELECT n FROM x",
            allowed_schemas=["datamart"],
        )

    def test_write_rejected(self):
        for sql in [
            "UPDATE datamart.t SET x=1",
            "DELETE FROM datamart.t",
            "SELECT * INTO x FROM datamart.t",
            "DROP TABLE datamart.t",
        ]:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLValidationError):
                    validate_select_only(sql, allowed_schemas=["datamart"])

    def test_cross_database_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select_only(
                "SELECT * FROM otherdb.datamart.fact_transaction",
                allowed_schemas=["datamart"],
            )

    def test_disallowed_schema_rejected(self):
        with self.assertRaises(SQLValidationError):
            validate_select_only(
                "SELECT * FROM secret.some_table",
                allowed_schemas=["datamart"],
            )

    def test_forbidden_word_in_string_not_rejected(self):
        validate_select_only(
            "SELECT * FROM datamart.fact_transaction WHERE source = 'dropbox'",
            allowed_schemas=["datamart"],
        )


if __name__ == "__main__":
    unittest.main()
