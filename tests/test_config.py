import os
import unittest
from unittest import mock

from config import ConfigError, load_config


BASE = {
    "FABRIC_TENANT_ID": "tenant",
    "FABRIC_CLIENT_ID": "client",
    "FABRIC_CLIENT_SECRET": "secret",
    "FABRIC_SQL_ENDPOINT": "example.datawarehouse.fabric.microsoft.com",
    "FABRIC_DATABASE": "dwh_report",
}


class ConfigTests(unittest.TestCase):
    def test_minimal_required_config(self):
        with mock.patch.dict(os.environ, BASE, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.warehouse_target.database, "dwh_report")
        self.assertEqual(cfg.allowed_adhoc_schemas, ("datamart",))

    def test_missing_secret_is_named_not_exposed(self):
        values = dict(BASE)
        values.pop("FABRIC_CLIENT_SECRET")
        with mock.patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ConfigError) as ctx:
                load_config()
        self.assertIn("FABRIC_CLIENT_SECRET", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
