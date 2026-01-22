from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
from jinja2 import Template
import sqlalchemy
import json
import re


class store_data_table_node:

    default_setup: NodeConfig = {
        "id": "StoreDataInTable",
        "name": "Store Data in Table",
        "description": "Insert provided data into a table using given database connection",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [
                {"name": "Connection"},
                {"name": "Data"}
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
            }
        ]
    }

    def __init__(self, node: Node):
        self.node = node
        configuration = node.data.get("configuration") or {}
        self.table_name = configuration.get("TableName")
        self.ddl = configuration.get("DDL")

    def parse_table_fields(self, ddl: str):
        """
        Extract column definitions and detect auto_increment, default values, etc.
        Returns: dict[column_name] = {"auto": bool, "default": any, "nullable": bool}
        """
        columns = {}
        try:
            # Extract everything between CREATE TABLE (...) block
            inside = re.search(r"\(([\s\S]*)\)", ddl)
            if not inside:
                return columns

            lines = inside.group(1).splitlines()
            for line in lines:
                line = line.strip().strip(",")
                # Skip constraints / keys
                if line.upper().startswith(("PRIMARY", "KEY", "CONSTRAINT", "FOREIGN")):
                    continue

                col_match = re.match(r"`?(\w+)`?\s+([\w()]+)(.*)", line)
                if not col_match:
                    continue

                name, col_type, rest = col_match.groups()
                rest_upper = rest.upper()

                columns[name] = {
                    "auto": "AUTO_INCREMENT" in rest_upper,
                    "default": None,
                    "nullable": "NOT NULL" not in rest_upper
                }

                default_match = re.search(r"DEFAULT\s+([^\s,]+)", rest, re.IGNORECASE)
                if default_match:
                    default_val = default_match.group(1).strip().strip("'").strip('"')
                    columns[name]["default"] = (
                        None if default_val in ["NULL", "null"] else default_val
                    )
        except Exception as e:
            self.node.LogEvent("DDL Parse Error", data={}, error=str(e))

        return columns

    def Run(self, connection, data):
        print("\n================= [StoreDataInTable] DEBUG START =================")

        conn_obj = data.get("Connection") or data.get("connection")
        insert_data = data.get("Data") or data.get("data")

        if not conn_obj:
            self.node.LogEvent("Store Data Error", data={}, error="Database connection missing")
            print("❌ Connection object missing — stopping execution.")
            print("================= [StoreDataInTable] DEBUG END =================\n")
            return self.node.TriggerAll()

        conn_str = conn_obj.get("connection_string")
        echo = conn_obj.get("echo", False)

        if not conn_str:
            self.node.LogEvent("Store Data Error", data={}, error="Invalid connection string")
            print("❌ Connection string missing — stopping execution.")
            print("================= [StoreDataInTable] DEBUG END =================\n")
            return self.node.TriggerAll()

        if not self.table_name:
            self.node.LogEvent("Store Data Error", data={}, error="Table name missing")
            print("❌ Table name missing — stopping execution.")
            print("================= [StoreDataInTable] DEBUG END =================\n")
            return self.node.TriggerAll()

        if isinstance(insert_data, str):
            try:
                insert_data = json.loads(insert_data)
            except Exception:
                self.node.LogEvent("Store Data Error", data={}, error="Invalid JSON input data")
                return self.node.TriggerAll()

        if not isinstance(insert_data, dict):
            self.node.LogEvent("Store Data Error", data={}, error="Data must be a JSON object")
            return self.node.TriggerAll()

        try:
            rendered_table = Template(self.table_name).render(**data)
        except Exception:
            rendered_table = self.table_name

        # --- Parse DDL to know what to insert ---
        table_fields = self.parse_table_fields(self.ddl or "")
        valid_columns = {}

        for col, meta in table_fields.items():
            if meta["auto"]:
                continue  # Skip AUTO_INCREMENT fields
            if col in insert_data:
                valid_columns[col] = insert_data[col]
            elif meta["default"] is not None:
                # Only include default if user provided value — else DB handles it
                continue
            elif not meta["nullable"]:
                # Required but missing
                self.node.LogEvent(
                    "Store Data Warning",
                    data={"column": col},
                    error=f"Required column '{col}' missing, skipping insert."
                )

        if not valid_columns:
            self.node.LogEvent("Store Data Error", data={}, error="No valid columns to insert")
            return self.node.TriggerAll()

        try:
            print("\n[StoreDataInTable] === Execution Started ===")
            print(f"🗃️ Table Name: {rendered_table}")
            print(f"📦 Data to Insert: {json.dumps(valid_columns, indent=2)}")

            engine = sqlalchemy.create_engine(conn_str, echo=echo)
            with engine.begin() as conn:
                columns = ", ".join(valid_columns.keys())
                placeholders = ", ".join([f":{key}" for key in valid_columns.keys()])
                query = f"INSERT INTO {rendered_table} ({columns}) VALUES ({placeholders})"

                result = conn.execute(sqlalchemy.text(query), valid_columns)

                print(f"✅ Query Executed Successfully. Result: {result.rowcount} row(s) affected.\n")

                self.node.LogEvent(
                    "Data Inserted Successfully",
                    data={"table": rendered_table, "inserted": valid_columns}
                )
                self.node.SetTargetPinData("Output", {"status": "success", "inserted": valid_columns})

        except Exception as e:
            print(f"❌ Error Executing Insert: {str(e)}\n")
            self.node.LogEvent(
                event="Store Data Error",
                error=str(e),
                data={"table": self.table_name}
            )

        print("[StoreDataInTable] === Execution Finished ===\n")
        return self.node.TriggerAll()
