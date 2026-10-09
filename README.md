# DSN Fabric MCP - installation and usage guide

This Python MCP server lets Claude Desktop query the existing DSN data in Microsoft Fabric using approved, server-owned SQL and reconciliation rules. It authenticates with a Microsoft Entra service principal, returns bounded previews, caches results locally, and exports Excel workbooks with provenance.

**Follow the setup steps in order.** Python packages alone are insufficient: you also need Microsoft ODBC Driver 18, real credentials, Fabric SQL permissions, and the existing DSN tables. The checks below separate installation, MCP startup, and live data access so you can identify the cause of a failure.

The main walkthrough uses **Windows PowerShell**. Run commands one at a time and resolve a failed step before continuing. macOS/Linux adaptations are included near the end.

## Contents

- [1. Download the prerequisites](#1-download-the-prerequisites)
- [2. Obtain Fabric credentials and permissions](#2-obtain-fabric-credentials-and-permissions)
- [3. Download the project](#3-download-the-project)
- [4. Install the Python dependencies](#4-install-the-python-dependencies)
- [5. Configure the app](#5-configure-the-app)
- [6. Verify installation and Fabric connectivity](#6-verify-installation-and-fabric-connectivity)
- [7. Connect Claude Desktop and run the server](#7-connect-claude-desktop-and-run-the-server)
- [8. Run your first analysis](#8-run-your-first-analysis)
- [Troubleshooting](#troubleshooting)
- [Configuration reference](#configuration-reference)
- [Architecture and project layout](#architecture-and-project-layout)
- [macOS and Linux](#macos-and-linux)
- [Maintenance, security, and data retention](#maintenance-security-and-data-retention)
- [Verification scope](#verification-scope)

## 1. Download the prerequisites

For the Windows walkthrough, use a 64-bit Windows workstation and 64-bit Python. Installers may require administrator or IT assistance; the app itself should run as your normal user.

| Prerequisite | Official download / instructions | What to install |
| --- | --- | --- |
| Python | [Python releases for Windows](https://www.python.org/downloads/windows/) | Python **3.13, 64-bit**, with `pip` and `venv`. In the traditional installer, enable **Add python.exe to PATH**. This is the locally verified Python series; the MCP SDK requires Python 3.10 or newer, but other versions have not been tested for this checkout. |
| Microsoft ODBC driver | [Microsoft ODBC Driver downloads](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server) | **ODBC Driver 18 for SQL Server**, using the Windows installer for your architecture. Driver 17 alone does not satisfy this app. `pip install pyodbc` installs the Python binding, not the Microsoft driver. |
| Visual C++ runtime, if required by your driver installer | [Microsoft Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) | Microsoft documents a separate runtime prerequisite for ODBC 18.6 and earlier; ODBC 18.7 and later do not require it to be preinstalled. Match the architecture when installing it. |
| Claude Desktop | [Download Claude Desktop](https://claude.com/download) | Install and sign in. Your organization must allow local MCP servers. Use the desktop app for this local stdio connection. |
| Git, if using `git clone` | [Git for Windows](https://git-scm.com/install/windows) | Install Git with command-line access. You can instead download a ZIP in step 3. |
| Fabric access | [Fabric service-principal access](https://learn.microsoft.com/en-us/fabric/data-warehouse/service-principals) | An existing, available Fabric warehouse/SQL analytics endpoint containing the DSN schema, plus the credentials and permissions in step 2. |

Install Python first, the Visual C++ runtime if required, then ODBC Driver 18, Git if needed, and Claude Desktop. On the Microsoft driver download page, select the **Windows x64 Driver 18 installer**, run the downloaded MSI, accept the license, and complete the installation. Keep Python and driver architectures aligned; step 6 checks the driver from the actual app interpreter.

The setup does not need a local SQL Server installation, an ODBC DSN, Node.js, Docker, Azure CLI, or Microsoft Excel. Excel is optional for viewing `.xlsx` files; `openpyxl` creates them.

After installing Python and Git, **open a new PowerShell window** and check:

```powershell
python --version
python -m pip --version
python -c "import struct; print('Python architecture:', struct.calcsize('P') * 8, 'bit')"
git --version
```

Expect Python 3.13.x and `64 bit`. Skip the Git check if using a ZIP. If `python` is unavailable or starts the Microsoft Store instead, fix PATH/app execution aliases or use the installed interpreter's full path. If the Python launcher is installed, `py -3.13 --version` can help select the intended version; the launcher is not required.

## 2. Obtain Fabric credentials and permissions

Ask your Entra/Fabric administrator for these values before attempting live queries:

| Value | Where it comes from | `.env` variable |
| --- | --- | --- |
| Directory/tenant ID | Entra app registration **Overview** | `FABRIC_TENANT_ID` |
| Application/client ID | App registration **Overview**; use the application ID, not its object ID | `FABRIC_CLIENT_ID` |
| Client secret **value** | App registration **Certificates & secrets** | `FABRIC_CLIENT_SECRET` |
| Warehouse SQL server hostname | Fabric warehouse/SQL analytics endpoint SQL connection details | `FABRIC_SQL_ENDPOINT` |
| Database/item name | Exact warehouse database name, normally `dwh_report` | `FABRIC_DATABASE` |
| MVD database and, if different, server | SQL analytics endpoint for `lh_transform`, if you need MVD | `FABRIC_TRANSFORM_DATABASE`, `FABRIC_TRANSFORM_SQL_ENDPOINT` |

If a new identity is needed, an authorized administrator can follow [Microsoft's app registration guide](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) and [credential creation guide](https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-credentials):

1. In the Microsoft Entra admin center, select the tenant that hosts Fabric, then **Entra ID > App registrations > New registration**.
2. Give the app a meaningful name, use your organization's approved account type (normally single tenant), and register it. Record the tenant and application/client IDs from **Overview**.
3. Open **Certificates & secrets > Client secrets > New client secret**, enter a description and approved expiry, then select **Add**.
4. Copy the secret **Value** immediately, not the Secret ID; record its expiry for rotation. The value cannot be retrieved again after leaving that page.

The Fabric administrator must grant the principal access to the warehouse item through Fabric item permissions or an appropriate workspace role, then grant SQL read access. Prefer item access and specific `SELECT` grants rather than broad write-capable roles. An Entra app registration or API-consent entry alone does not grant access to warehouse rows. See [Microsoft's service-principal permissions guidance](https://learn.microsoft.com/en-us/fabric/data-warehouse/service-principals).

The curated queries expect these existing objects, with the columns referenced in [queries/](queries/):

| Target database | Required objects across the supported reports |
| --- | --- |
| `dwh_report` | `datamart.fact_transaction`, `datamart.dim_entity`, `datamart.dim_service`, `datamart.dim_customer`, `datamart.dim_parent_customer`, `datamart.dim_vehicle` |
| `lh_transform`, for MVD only | `mvd.transaction` |

There is no migration, table-creation, or sample-data step in this repository. Changing a database name in `.env` does not adapt the SQL to a different schema. Catalog results also depend on the principal's metadata visibility.

The workstation needs HTTPS access to Microsoft Entra for tokens and SQL/TDS access to Fabric. Microsoft documents outbound TCP **1433** and relevant Power BI/SQL service tags; protocol-aware firewalls must handle the connection as SQL/TDS. Private endpoints may require your organization's VPN and DNS configuration. Ask IT to follow [Fabric connectivity guidance](https://learn.microsoft.com/en-us/fabric/data-warehouse/connectivity).

## 3. Download the project

### Option A: Clone with Git

Choose a stable, writable folder. This example uses your Windows user folder:

```powershell
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\source" | Out-Null
Set-Location "$env:USERPROFILE\source"
git clone https://github.com/tejashree-dsn/dsn-fabric-mcp_server.git
Set-Location .\dsn-fabric-mcp_server
```

If GitHub requests authentication, use an account with repository access. If you already have the project, open PowerShell in its existing folder instead of cloning over it.

### Option B: Download a ZIP

Open the [repository](https://github.com/tejashree-dsn/dsn-fabric-mcp_server), sign in if required, select **Code > Download ZIP**, and extract it completely. Open PowerShell in the extracted folder containing `server.py`. GitHub's extracted folder name may include the branch name; use your actual path in later steps.

Confirm you are in the project root:

```powershell
Get-Location
Get-Item .\server.py, .\requirements.txt, .\.env.example, .\queries
```

Keep the whole folder, including `queries/`. Do not launch from inside the ZIP. Moving/renaming the folder later requires updating Claude's paths and recreating the virtual environment at the new location.

## 4. Install the Python dependencies

From the project root, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

To select Python explicitly, replace only the first command with `py -3.13 -m venv .venv` or invoke the full path to Python 3.13. Subsequent commands use the project's interpreter.

Expect a successful install and `No broken requirements found.` Activation is unnecessary: using `.venv\Scripts\python.exe` directly avoids PowerShell activation-policy errors and installs into the environment Claude will use.

The direct dependencies in [requirements.txt](requirements.txt) are:

| Package | Purpose |
| --- | --- |
| `mcp>=2.0,<3.0` | MCP tools and stdio transport. This code uses the **2.x `MCPServer` API**. |
| `pydantic>=2.7,<3.0` | Tool input/output models and validation. |
| `pyodbc>=5.0` | Python interface to Microsoft ODBC Driver 18. |
| `python-dotenv>=1.0` | Load the project-local `.env`. |
| `azure-identity>=1.15` | SQL tokens using `ClientSecretCredential`. |
| `openpyxl>=3.1` | Excel exports and provenance sheets. |

Use this repository's requirements rather than an older MCP tutorial's dependencies. The [MCP package documentation](https://pypi.org/project/mcp/) describes the SDK version transition. A corporate mirror must provide a compatible stable 2.x release and its dependencies. There is no lockfile, so versions can change between installs; rerun the preflight checks after installing/upgrading.

## 5. Configure the app

Create `.env` next to `server.py`, preserving an existing configuration:

```powershell
if (-not (Test-Path -LiteralPath .\.env)) {
    Copy-Item -LiteralPath .\.env.example -Destination .\.env
}
notepad .\.env
```

Replace the required entries with your actual values. These are placeholders, not working credentials:

```dotenv
FABRIC_TENANT_ID=your-directory-tenant-id
FABRIC_CLIENT_ID=your-application-client-id
FABRIC_CLIENT_SECRET='your-client-secret-value'
FABRIC_SQL_ENDPOINT=your-real-endpoint.datawarehouse.fabric.microsoft.com
FABRIC_DATABASE=dwh_report
```

- Save the exact filename **`.env`**, not `.env.txt`. Windows may hide extensions; `Get-Item -Force .\.env` confirms the file exists.
- Use the SQL **server hostname**, not an `https://` URL, workspace URL, warehouse ID, or full `Server=...;Database=...` connection string. Extract the server and database into separate variables.
- Use the secret's value. Quote it if it contains characters dotenv could interpret, such as a comment marker or spaces; follow dotenv quoting rules if the value itself contains quotes.
- `FABRIC_DATABASE` is required even when its name is `dwh_report`.
- `.env` is read from the application directory, independent of Claude's working directory. Existing process environment variables take precedence because `load_dotenv(..., override=False)` is used. Restart Claude after changing configuration.

### Set output folders explicitly

The supplied `.env.example` has **blank** `FABRIC_EXPORT_DIR` and `FABRIC_RESULT_CACHE_DIR` entries. In the current code, a blank path becomes `.` (the process working directory), rather than the intended default folder. This can place data somewhere unexpected or cause a permissions error when Claude launches the server.

Before saving `.env`, choose one approach:

1. **Recommended:** replace the two blank entries with absolute, writable paths. Forward slashes work on Windows. Replace the user/folder below with your own:

   ```dotenv
   FABRIC_EXPORT_DIR=C:/Users/YOUR_WINDOWS_USER/source/dsn-fabric-mcp_server/exports
   FABRIC_RESULT_CACHE_DIR=C:/Users/YOUR_WINDOWS_USER/source/dsn-fabric-mcp_server/runtime/results
   ```

2. Delete or comment out **both entries entirely**. When the variables are absent from both `.env` and the process environment, the code defaults to `exports/` and `runtime/results/` under the application folder.

Use `(Get-Location).Path` to find your real project path. Relative custom paths depend on the launching process's working directory. The app creates output folders when needed, but their parent location must be writable by the user running Claude.

### Optional MVD connection

For MVD, configure its database and, only if necessary, its different server:

```dotenv
FABRIC_TRANSFORM_DATABASE=lh_transform
# Only set this when the transform endpoint differs from the warehouse endpoint:
# FABRIC_TRANSFORM_SQL_ENDPOINT=your-transform-endpoint.datawarehouse.fabric.microsoft.com
```

If `FABRIC_TRANSFORM_SQL_ENDPOINT` is blank/absent, the warehouse endpoint is reused. If you do not need MVD, remove/comment out `FABRIC_TRANSFORM_DATABASE=lh_transform` from the example. The principal needs separate access to the transform database for MVD.

`FABRIC_WORKSPACE_ID` and `FABRIC_WAREHOUSE_ID` are optional metadata, not SQL connection settings. Leave them blank if unnecessary. Keep numeric defaults unless you have a specific reason to change them.

## 6. Verify installation and Fabric connectivity

Run these from the project root with the same interpreter as the installation.

### A. Verify imports and the native driver

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import server; print('Server imports OK')"
.\.venv\Scripts\python.exe -c "import pyodbc; drivers = pyodbc.drivers(); print(drivers); assert 'ODBC Driver 18 for SQL Server' in drivers, 'Install Microsoft ODBC Driver 18 for SQL Server for this Python architecture'"
```

Expect `Server imports OK` and a driver list containing **exactly** `ODBC Driver 18 for SQL Server`. This checks the driver visible to this Python without contacting Fabric.

### B. Validate configuration without printing credentials

```powershell
.\.venv\Scripts\python.exe -c "from config import load_config; c = load_config(); print('Configuration loaded; credentials not displayed.'); print('Export folder:', c.export_dir.resolve()); print('Cache folder:', c.result_cache_dir.resolve()); print('Transform configured:', c.transform_target is not None)"
```

Expect the intended output folders and no `ConfigError`. This validates required values and numeric settings; it cannot prove that credentials, endpoints, permissions, or directory write access are correct.

### C. Run offline unit tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

The current suite has **18 tests** and should finish with `OK`. It checks configuration, query planning/date rules, SQL validation, and cache paging. It does not contact Fabric or exercise every report against the live schema.

### D. Check live warehouse authentication and connectivity

```powershell
.\.venv\Scripts\python.exe -c "from config import load_config; from fabric_client import FabricClient; h = FabricClient(load_config()).health_check(); print(h); raise SystemExit(0 if h['status'] == 'ok' else 1)"
```

Expect `status: 'ok'` and `connection: 'successful'`. This acquires an Entra token and runs `SELECT 1 AS ok` against the configured warehouse. It checks connectivity, not access to every DSN table. `transform_configured: True` only means a transform target was configured; it does **not** test MVD access.

### E. Check one real DSN query

```powershell
.\.venv\Scripts\python.exe -m tests.integration_test
```

Use the **module command above**, from the project root. Running `python tests\integration_test.py` directly can fail with `ModuleNotFoundError: No module named 'config'` because the application root is not on that invocation's import path.

The integration script checks warehouse health and retrieves at most five `core_transactions` rows for **June 2026**. Expect `ok` health followed by `core_transactions preview`. Zero rows can be legitimate for an empty period. Other reports and MVD need separate live checks.

**`NOT RUN: configuration unavailable` is a skip, not a successful connection test**, even though this script returns exit code 0 in that case. Complete `.env` and repeat B-E. The preview may contain business data; check it before sharing.

## 7. Connect Claude Desktop and run the server

The server uses **MCP over stdio**, not a browser page or HTTP port. Claude Desktop starts and owns the Python process. You do not need a separate terminal server running.

### A. Optional manual startup check

```powershell
.\.venv\Scripts\python.exe .\server.py
```

Expect a stderr log containing `Starting dsn-fabric-mcp (stdio transport)`. The process then waits for MCP messages on stdin. Waiting is normal; it is not an interactive SQL prompt. Use **Ctrl+C** to stop this check. Startup alone does not validate `.env` or connect to Fabric: services initialize lazily when tools are called.

### B. Find both absolute paths

```powershell
(Resolve-Path -LiteralPath .\.venv\Scripts\python.exe).Path
(Resolve-Path -LiteralPath .\server.py).Path
```

Use these exact paths in the config. The checked-in [configuration example](claude_desktop_config.example.json) contains placeholders, including an example folder name; replace all of them.

### C. Edit Claude's configuration

Open Claude Desktop **Settings > Developer > Edit Config** (Developer may be under Desktop app settings). On Windows, the file is:

```text
%APPDATA%\Claude\claude_desktop_config.json
```

Add this server entry, replacing the sample user/folder with your actual paths:

```json
{
  "mcpServers": {
    "dsn-fabric-mcp": {
      "command": "C:\\Users\\YOUR_WINDOWS_USER\\source\\dsn-fabric-mcp_server\\.venv\\Scripts\\python.exe",
      "args": [
        "C:\\Users\\YOUR_WINDOWS_USER\\source\\dsn-fabric-mcp_server\\server.py"
      ]
    }
  }
}
```

If `mcpServers` already contains servers, add only the `dsn-fabric-mcp` entry inside it and preserve the others. JSON requires escaped backslashes (`\\`), correct commas, and no comments/trailing commas. `command` must be the Python executable, and `args` must contain `server.py`; do not use an activation script or add shell quotes inside path strings.

Validate the saved JSON:

```powershell
Get-Content -Raw -LiteralPath "$env:APPDATA\Claude\claude_desktop_config.json" | ConvertFrom-Json | Out-Null
```

A successful parse has no output. Keep credentials in `.env`; this JSON needs no secrets.

### D. Restart and verify the tools

Fully quit Claude using **Quit/Exit from its system tray icon**, then reopen it. Closing only the window may leave the old process running. The [MCP desktop setup guide](https://modelcontextprotocol.io/docs/develop/build-server) describes configuration/restart behavior; [Claude's local MCP help](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop) explains connection status and tools.

Check Developer settings or the chat's **+ > Connectors** menu for `dsn-fabric-mcp` and these five tools:

```text
dsn_query
dsn_catalog
dsn_result
dsn_execute_ad_hoc_sql
health_check
```

Ask Claude: **"Use the dsn-fabric-mcp health_check tool and show the connection status."** Confirm `status=ok`. A connected MCP process with failing health still needs Fabric configuration/access repairs.

## 8. Run your first analysis

Start with a known period and approved tools. For example:

1. "Use dsn_catalog to list the available reports."
2. "Use dsn_query to show core transactions for June 2026, grouped by month and agency, with a 10-row preview."
3. "Use dsn_result to export that query_id to Excel and tell me its local export_path."

Pick a period containing data. A smaller preview limits what Claude receives, but the server still runs the report and caches rows up to its per-dataset cap.

### Tool inputs

`dsn_query`, `dsn_catalog`, and `dsn_result` take a parameter named **`request`**. These examples show complete tool arguments including that wrapper. `health_check` takes `{}`; the ad-hoc tool takes `sql` and `limit` directly.

**Discover reports or an exact stored customer name:**

```json
{
  "request": {
    "action": "list_reports"
  }
}
```

```json
{
  "request": {
    "action": "list_parent_customers",
    "search": "Morgan",
    "limit": 20
  }
}
```

**Run a preview:**

```json
{
  "request": {
    "report": "core_transactions",
    "year": 2026,
    "month": 6,
    "grain": "month_agency",
    "result_mode": "preview",
    "preview_rows": 10
  }
}
```

The response includes `query_id`, scope, methodology/version, warnings, and dataset names, columns, counts, previews, and truncation flags. Reuse the returned `query_id` for paging/export instead of querying Fabric again.

**Export a cached result:**

```json
{
  "request": {
    "action": "export",
    "query_id": "REPLACE_WITH_THE_RETURNED_QUERY_ID"
  }
}
```

**Page a cached dataset:**

```json
{
  "request": {
    "action": "page",
    "query_id": "REPLACE_WITH_THE_RETURNED_QUERY_ID",
    "dataset": "core_transactions",
    "offset": 10,
    "limit": 10
  }
}
```

Offsets start at 0. Use the exact returned dataset name. Multi-dataset reports require `dataset` for paging; `action=metadata` lists datasets/provenance. Export writes all cached datasets on the MCP workstation and returns `export_path`/`export_uri`; a local file URI is not a hosted download link.

### Supported reports and filters

Every report needs `year` (optionally `month` or contiguous `months`) or both `from_date` and `to_date`.

| Report | Additional options | Notes |
| --- | --- | --- |
| `core_transactions` | `agency_codes`, `parent_customer`, `grain` | Distinct core/all counts. Use aggregate summary for authoritative total revenue because dimension joins can fan out revenue. |
| `parent_customer_detail` | **Required** exact `parent_customer`; optional `agency_codes` | Transaction detail including vehicle/customer dimensions. Resolve the stored name first. |
| `dealer_service_summary` | `parent_customer`, `agency_codes` | Counts by parent customer, service, and month. |
| `aggregate_summary` | `include_all` | `Transaction Count by Entity` and `Revenue by Source` datasets. Rejects agency/parent filters. `include_all=true` disables provisional exclusions for comparison. |
| `reference_summary` | `agency_codes` | Two datasets with reference source/entity scope; rejects parent filtering. |
| `eomv_retail` | Date window only | Fixed EOMV/Express Lane scope; rejects agency/parent filters. |
| `mvd` | `agency_codes` | Transform target and `mvd.transaction`; rejects parent filtering. |

Dates use **inclusive start / exclusive end**: June 2026 is `from_date="2026-06-01"`, `to_date="2026-07-01"`, not June 30 as the upper bound. Supply both explicit dates and do not mix them with `month`/`months`. `year` alone selects the full calendar year; `months` must be contiguous, such as `[1,2,3]`. Agency codes are trimmed/upper-cased. Parent names use SQL equality, subject to the database collation.

Core grains are `month`, `month_agency`, `month_parent_customer`, `month_agency_parent_customer`, and `month_agency_parent_customer_dealer` (default). Use `grain` only for core transactions and `include_all` only for aggregate summary. `result_mode="export"` can generate Excel immediately in `dsn_query`.

Other catalog actions: `methodology` (optionally with `report`), `list_agencies`, `list_tables`, `describe_table` (requires `schema_name` and `table_name`), and `search_columns` (requires `search`). Catalog queries use the warehouse target, not the transform target.

`dsn_execute_ad_hoc_sql` is a fallback for one read-only SELECT/CTE against the warehouse. Its default `limit` is 200. It rejects obvious write/admin operations and explicit cross-database references and checks configured schemas. Standard metrics should use `dsn_query`; SQL validation is defense in depth, while principal permissions remain the authorization boundary.

### Optional analytics skill

Guidance is in [skill/dsn-fabric-analytics/](skill/dsn-fabric-analytics/), with a [packaged skill ZIP](skill/dsn-fabric-analytics.zip). It teaches report selection and terminology; executable SQL/calculations stay in the server.

The optional skill does not install dependencies, register the server, or grant Fabric access. If your Claude account supports custom skill uploads, upload the ZIP through its skill-management interface. The MCP tools work independently of the skill.

## Troubleshooting

Start at the earliest failing verification step. Fully quit/reopen Claude after configuration or dependency changes.

| Symptom | What to check / how to resolve |
| --- | --- |
| `python`/`git` not recognized | Reopen PowerShell; check PATH or use Python's full path. ZIP download avoids the Git requirement. |
| `Activate.ps1 cannot be loaded` | Use `.venv\Scripts\python.exe` directly; activation/changing execution policy are unnecessary. |
| Venv creation fails or pip is missing | Confirm Python includes pip/venv and you can write to the project and temporary directories. Once permissions are fixed, retry `python -m venv .venv`; repair Python if its bundled pip is missing. |
| No matching distribution for MCP 2.x | Verify Python 3.10+ and a package index/mirror with stable MCP 2.x. Ask IT to refresh an outdated mirror; do not downgrade this app to 1.x. |
| Missing `mcp`, `pyodbc`, or another package | Install requirements with the venv interpreter and confirm Claude uses that same interpreter. |
| Missing `mcp.server.mcpserver` | Check `.venv\Scripts\python.exe -m pip show mcp`; install this repository's requirements into the correct venv. |
| Missing `config` when testing | Use `.venv\Scripts\python.exe -m tests.integration_test` from the project root, not the integration script as a file. |
| Driver absent, `IM002`, or "Could not load ODBC Driver 18" | Install native Driver 18 for the Python architecture and its runtime if required; repeat `pyodbc.drivers()`. Some ODBC interface errors are connection-related; inspect the underlying log error. |
| `Missing required configuration: ...` | Check `.env` location/name and the five nonblank required values. Check for stale process variables overriding the file. |
| Setting must be an integer / >= 1 | Use a positive integer without units or remove the setting to use its default. Blank numeric values are invalid. |
| Service-principal authentication fails | Check tenant/client IDs, secret **value**, expiry, and HTTPS access to Entra. Object IDs/secret IDs are not substitutes. |
| SQL login/access fails after token acquisition | Check exact database name, Fabric item/workspace access, and SQL permissions; have the administrator verify both access layers. |
| Timeout, DNS, or connection failure | Check hostname, VPN/private DNS, active Fabric capacity, SQL/TDS firewall rules, and endpoint availability. A higher timeout cannot fix wrong credentials or blocked access. |
| Certificate/SSL failure | Have IT verify trusted certificates/TLS inspection. The client uses `Encrypt=yes;TrustServerCertificate=no`; preserve certificate validation. |
| Health is `ok`, but a report fails on objects/columns/permissions | `SELECT 1` does not read DSN tables. Check the configured database, template schema, and principal's read access. |
| Warehouse works, MVD fails | Configure the transform database/server and grant access to `mvd.transaction` there. Warehouse health does not test it. |
| Query template missing | Keep `queries/` alongside `query_builder.py`; restore the missing file from the distribution. |
| Tool validation failure | Use the `request` wrapper, valid enums/date windows, and report-supported filters. Preview/catalog/page limits are 1-500. |
| Parent detail returns no rows | Search `dsn_catalog` with `action=list_parent_customers`, use the stored name, and verify the dates. |
| Claude disconnected / tools absent | Validate JSON, both absolute paths, imports, full restart, Developer status/logs, and organizational MCP policy. |
| Cache/export permissions fail or files appear elsewhere | Replace blank paths with absolute writable folders or remove those settings. Check the app user's permissions/disk space. |
| Workbook cannot be written | Check directory access/disk space and close a workbook locking the destination. The file is local to the MCP workstation. |
| Result not found or expired | Rerun `dsn_query`; cleanup, deletion, or a changed cache folder can remove an old query ID. |
| `truncated=true` | The per-dataset cap was reached. Paging/export cannot recover omitted rows. Narrow scope or deliberately raise the cap and rerun. |

For a basic Windows network check, substitute your real SQL hostname:

```powershell
Test-NetConnection -ComputerName your-real-endpoint.datawarehouse.fabric.microsoft.com -Port 1433
```

`TcpTestSucceeded=True` tests TCP only, not SQL authentication, TLS, table access, or complete firewall routing. Follow [Microsoft's connectivity guidance](https://learn.microsoft.com/en-us/fabric/data-warehouse/connectivity) if health still fails.

Use Claude's **Developer** settings to open MCP logs. Look for `mcp.log` and `mcp-server-dsn-fabric-mcp.log` in the log directory shown by your installation. This app logs to **stderr**, keeping stdout available for MCP messages; do not add ordinary `print()` output to its protocol stream. Remove business data/credentials before sharing logs.

## Configuration reference

Settings are loaded in [config.py](config.py). Numeric values must be integers >= 1. Explicitly blank settings do not necessarily use defaults.

| Variable | Default when absent | Behavior |
| --- | --- | --- |
| `FABRIC_TENANT_ID` | Required | Entra tenant ID. |
| `FABRIC_CLIENT_ID` | Required | Application/client ID. |
| `FABRIC_CLIENT_SECRET` | Required | Secret value. |
| `FABRIC_SQL_ENDPOINT` | Required | Warehouse SQL hostname. |
| `FABRIC_DATABASE` | Required | Database name, normally `dwh_report`. |
| `FABRIC_TRANSFORM_DATABASE` | Unconfigured | Enables MVD target. The example sets `lh_transform`; remove if unused. |
| `FABRIC_TRANSFORM_SQL_ENDPOINT` | Warehouse endpoint | Different transform server; blank also falls back. |
| `FABRIC_WORKSPACE_ID`, `FABRIC_WAREHOUSE_ID` | None | Metadata; not used for SQL routing/authentication. |
| `FABRIC_ADHOC_ALLOWED_SCHEMAS` | `datamart` | Comma-separated nonempty allowlist for ad-hoc two-part object names; does not restrict curated templates/catalog. |
| `FABRIC_EXPORT_DIR` | `<app>/exports` | Default applies when absent. **Blank means the current working directory.** Prefer absolute paths. |
| `FABRIC_RESULT_CACHE_DIR` | `<app>/runtime/results` | Default applies when absent. **Blank means the current working directory.** Prefer absolute paths. |
| `FABRIC_RESULT_CACHE_TTL_HOURS` | `24` | Cache cleanup threshold; see retention below. |
| `FABRIC_CONNECTION_TIMEOUT_SECONDS` | `30` | ODBC connection timeout. |
| `FABRIC_QUERY_TIMEOUT_SECONDS` | `180` | Attempts cursor timeout; driver/pyodbc support varies. Not a guaranteed wall-clock deadline. |
| `FABRIC_FETCH_SIZE` | `1000` | Rows fetched per batch. |
| `FABRIC_MAX_RESULT_ROWS` | `250000` | Cached rows per curated dataset; excess rows produce truncation warnings. |
| `FABRIC_MAX_ADHOC_ROWS` | `2000` | Maximum ad-hoc `limit`; tool defaults to 200. |
| `FABRIC_DEFAULT_PREVIEW_ROWS` | `100` | Loaded, but **currently unused for changing the request default**. Set `preview_rows` in the request. |
| `FABRIC_MAX_PREVIEW_ROWS` | `500` | Additional curated preview cap. Request model also has a hard maximum of 500; paging/catalog limits are separate. |

`QueryRequest.preview_rows` defaults to 100. `ResultRequest.limit` defaults to 100 and `CatalogRequest.limit` to 200; both accept at most 500. Preview limits do not limit queried/cached rows.

## Architecture and project layout

```text
Claude Desktop  <-- optional analytics skill guides tool choice
      |
      | MCP / stdio
      v
server.py
  |-- dsn_query                 approved reports/methodology
  |-- dsn_catalog               discovery and metadata
  |-- dsn_result                cached paging/metadata/XLSX
  |-- dsn_execute_ad_hoc_sql     bounded SELECT/CTE fallback
  `-- health_check              warehouse SELECT 1
      |
      | Entra SQL token -> ODBC Driver 18
      v
Microsoft Fabric SQL endpoints
  |-- dwh_report                warehouse reports
  `-- lh_transform              optional MVD

Local storage: runtime/results/ (cache), exports/ (workbooks)
```

| File/folder | Responsibility |
| --- | --- |
| [server.py](server.py) | Five tools, expected errors, stdio transport. |
| [config.py](config.py), [.env.example](.env.example) | Configuration, defaults, required values. |
| [fabric_client.py](fabric_client.py) | Token acquisition/refresh, ODBC, streaming, health. |
| [models.py](models.py) | Typed tool contracts/validation. |
| [business_rules.py](business_rules.py) | Methodology/version and approved lists. |
| [query_builder.py](query_builder.py), [queries/](queries/) | Dates, filters/grains, parameterized plans/templates. |
| [query_service.py](query_service.py) | Execute datasets, cache, previews/warnings, optional export. |
| [catalog_service.py](catalog_service.py) | Targeted warehouse discovery. |
| [result_store.py](result_store.py) | JSONL cache, metadata, paging, cleanup. |
| [exporter.py](exporter.py) | Excel and `_pull_info` provenance. |
| [sql_validator.py](sql_validator.py) | Defense-in-depth fallback SQL checks. |
| [tests/](tests/) | Offline tests and manual live integration check. |
| [claude_desktop_config.example.json](claude_desktop_config.example.json) | Example launcher configuration. |
| [skill/dsn-fabric-analytics/](skill/dsn-fabric-analytics/) | Optional interpretation/tool-selection guidance. |

The curated approach preserves distinct counts, exclusive date bounds, EFS/non-EFS core definitions, aggregate/reference scopes, EOMV rules, MVD access, and exact parent detail. The model selects a workflow; the server owns its calculation.

## macOS and Linux

Windows is the locally verified path. For another OS, install a compatible Python, native **Microsoft ODBC Driver 18**, and its driver manager using Microsoft's [macOS instructions](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/install-microsoft-odbc-driver-sql-server-macos) or [Linux instructions](https://learn.microsoft.com/en-us/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server). Follow the instructions for your OS/distribution and architecture.

From the project root:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip check
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

Some Linux distributions provide `venv` as a separate package for the chosen Python version. Configure `.env` with absolute Unix paths, then run the import, driver, config, health, and integration checks above with `./.venv/bin/python`.

Claude Desktop configuration: macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Linux `~/.config/Claude/claude_desktop_config.json`. Set `command` to absolute `<project>/.venv/bin/python` and `args` to absolute `<project>/server.py`. Desktop availability/policy may vary; see the [MCP setup guide](https://modelcontextprotocol.io/docs/develop/build-server). These platforms have not been exercised for this update.

## Maintenance, security, and data retention

- Rerun install/verification after updates and restart Claude. Recreate the venv and update absolute paths after moving the project or replacing Python.
- Rotate secrets through your administrator, update `.env`, and restart before expiry. Authentication uses SQL token scope `https://database.windows.net/.default`.
- Keep `.env`, `.venv/`, `runtime/`, and `exports/` out of source control/team ZIPs; [.gitignore](.gitignore) excludes standard paths. Protect custom output folders too. Recipients need their own venv/configuration and authorized credentials.
- Cached JSONL/metadata cleanup runs at store initialization and new-query creation, using query-folder modification time. It is **not a background timer or guaranteed deletion exactly at 24 hours**. Restarting does not otherwise erase valid caches.
- Excel exports are **not deleted by cache TTL cleanup**. Apply separate retention rules and secure both output locations with adequate disk space.
- A truncated cache produces a truncated export. Narrow scope before raising the per-dataset cap; account for memory/disk and Excel's 1,048,576 worksheet-row maximum including the header. The exporter does not split oversized datasets across sheets.
- `_pull_info` records report, scope, methodology version, warnings, dataset counts/truncation, templates, and query hashes. Inspect it when reconciling results.
- Grant only needed read access. Principal permissions are the security boundary; do not expose credentials/endpoints as model-supplied tool inputs.
- When intentionally changing calculations, update `BUSINESS_RULE_VERSION` in `business_rules.py`, review affected templates/query builder, and verify against an approved live reconciliation dataset.

## Verification scope

During this README update on **2026-10-09**, a fresh Windows x64 venv installed the existing requirements with Python **3.13.14**, MCP **2.3.0**, Pydantic **2.14.0**, pyodbc **5.3.0**, python-dotenv **1.2.4**, azure-identity **1.26.0**, and openpyxl **3.1.5**. Dependency consistency, server import, Driver 18 visibility, and the **18 offline tests** passed. An MCP stdio startup/handshake check discovered all five tools, confirmed their request schemas, and exercised the missing-configuration health response without contacting Fabric. The README's PowerShell syntax, JSON examples, request models, local links, and contents anchors were also validated.

No real `.env` credentials were available in this checkout. Live Fabric authentication, table permissions, report results, MVD access, and Claude Desktop operation still require steps 6-8 on the recipient's machine. External permissions, network policies, and future dependency versions can change; use the staged checks to establish what works in your environment.
