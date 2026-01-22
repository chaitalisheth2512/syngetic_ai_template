from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
from jinja2 import Template
import sqlalchemy
import json
import re
from datetime import datetime, date
from decimal import Decimal


class fetch_data_table_node:
    default_setup: NodeConfig = {
        "id": "FetchDataFromTable",
        "name": "Fetch Data from Table",
        "description": "Fetch data from a database table using given connection and filters",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [
                {"name": "Connection"},
                {"name": "Filter"}  # Optional filter input
            ],
            "output_pins": [{"name": "Output"}],
            "next_pins": [{"name": "Next"}]
        },
        "fields": [
            {
                "id": "TableName",
                "label": "Table Name",
                "type": FieldType.SINGLE_LINE,
                "width": "100%"
            },
            {
                "id": "DDL",
                "label": "Table Schema (DDL Fields JSON)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Take",
                "label": "Take (Limit Rows)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            },
            {
                "id": "Skip",
                "label": "Skip (Offset Rows)",
                "type": FieldType.SINGLE_LINE,
                "width": "50%"
            }
        ]
    }

    def __init__(self, node: Node):
        self.node = node
        configuration = node.data.get("configuration") or {}
        self.table_name = configuration.get("TableName")
        self.ddl = configuration.get("DDL")
        self.take = configuration.get("Take")
        self.skip = configuration.get("Skip")

    def parse_table_fields(self, ddl: str):
        """
        Extract column names from DDL (reuse logic from StoreData node)
        """
        columns = []
        try:
            inside = re.search(r"\(([\s\S]*)\)", ddl)
            if not inside:
                return columns

            lines = inside.group(1).splitlines()
            for line in lines:
                line = line.strip().strip(",")
                if line.upper().startswith(("PRIMARY", "KEY", "CONSTRAINT", "FOREIGN")):
                    continue
                col_match = re.match(r"`?(\w+)`?\s+([\w()]+)", line)
                if col_match:
                    name, _ = col_match.groups()
                    columns.append(name)
        except Exception as e:
            self.node.LogEvent("DDL Parse Error", data={}, error=str(e))
        return columns

    def _safe_serialize_value(self, value):
        """Convert non-JSON-serializable types into safe values"""
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except Exception:
                return str(value)
        return value

    def Run(self, connection, data):
        print("\n================= [FetchDataFromTable] DEBUG START =================")
        print("Incoming data keys:", list(data.keys()))
        print("Incoming data full payload:", json.dumps(data, indent=2, default=str))

        conn_obj = data.get("Connection") or data.get("connection")
        filter_data = data.get("Filter") or data.get("filter") or {}

        print("Extracted connection object:", conn_obj)
        print("Extracted filter data:", filter_data)

        if not conn_obj:
            self.node.LogEvent("Fetch Data Error", data={}, error="Database connection missing")
            print("❌ Connection object missing — stopping execution.")
            return self.node.TriggerAll()

        conn_str = conn_obj.get("connection_string")
        echo = conn_obj.get("echo", False)

        if not conn_str:
            self.node.LogEvent("Fetch Data Error", data={}, error="Invalid connection string")
            print("❌ Connection string missing — stopping execution.")
            return self.node.TriggerAll()

        if not self.table_name:
            self.node.LogEvent("Fetch Data Error", data={}, error="Table name missing")
            print("❌ Table name missing — stopping execution.")
            return self.node.TriggerAll()

        try:
            rendered_table = Template(self.table_name).render(**data)
        except Exception:
            rendered_table = self.table_name

        # --- Build Query ---
        where_clauses = []
        params = {}

        if isinstance(filter_data, str):
            try:
                filter_data = json.loads(filter_data)
            except Exception:
                filter_data = {}

        if isinstance(filter_data, dict) and filter_data:
            for key, value in filter_data.items():
                where_clauses.append(f"{key} LIKE :{key}")
                params[key] = f"%{value}%"

        where_sql = " AND ".join(where_clauses)
        limit_sql = f"LIMIT {self.take}" if self.take else ""
        offset_sql = f"OFFSET {self.skip}" if self.skip else ""

        base_query = f"SELECT * FROM {rendered_table}"
        if where_sql:
            base_query += f" WHERE {where_sql}"
        if limit_sql:
            base_query += f" {limit_sql}"
        if offset_sql:
            base_query += f" {offset_sql}"

        print("\n[FetchDataFromTable] === Execution Started ===")
        print(f"🗃️ Table Name: {rendered_table}")
        print(f"🔍 Final Query: {base_query}")
        print(f"📦 Query Params: {params}")

        try:
            engine = sqlalchemy.create_engine(conn_str, echo=echo)
            with engine.begin() as conn:
                result = conn.execute(sqlalchemy.text(base_query), params)
                rows = []
                for row in result:
                    safe_row = {
                        k: self._safe_serialize_value(v) for k, v in dict(row._mapping).items()
                    }
                    rows.append(safe_row)

                print(f"✅ Query Executed Successfully. Fetched {len(rows)} row(s).\n")

                self.node.LogEvent(
                    "Data Fetched Successfully",
                    data={"table": rendered_table, "rows": len(rows)}
                )

                # ✅ Safe JSON data passed through output pin
                self.node.SetTargetPinData(
                    "Output",
                    {"status": "success", "rows": rows}
                )

        except Exception as e:
            print(f"❌ Error Fetching Data: {str(e)}\n")
            self.node.LogEvent(
                event="Fetch Data Error",
                error=str(e),
                data={"table": self.table_name}
            )
            self.node.SetTargetPinData("Output", {"status": "error", "message": str(e)})

        print("[FetchDataFromTable] === Execution Finished ===\n")
        return self.node.TriggerAll()
