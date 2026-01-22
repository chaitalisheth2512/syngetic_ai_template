from workflow.workflow_datatypes import Pin, NodeConfig, FieldType
from workflow.workflow_executor import Node
import json


class database_node:
    default_setup: NodeConfig = {
        "id": "DatabaseNode",
        "name": "Database Connection",
        "description": "Connect to any database using SQLAlchemy connection string",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [],
            "output_pins": [{"name": "Connection"}],
            "next_pins": [{"name": "Next"}]
        },
        "fields": [
            {
                "id": "DBType",
                "label": "Database Type",
                "type": FieldType.SINGLE_SELECT,
                "options": ["PostgreSQL", "MySQL", "SQLite", "MSSQL", "Oracle"],
                "width": "50%"
            },
            {"id": "Host", "label": "Host", "type": FieldType.SINGLE_LINE, "width": "50%"},
            {"id": "Port", "label": "Port", "type": FieldType.SINGLE_LINE, "width": "25%"},
            {"id": "Database", "label": "Database Name", "type": FieldType.SINGLE_LINE, "width": "50%"},
            {"id": "Username", "label": "Username", "type": FieldType.SINGLE_LINE, "width": "50%"},
            {"id": "Password", "label": "Password", "type": FieldType.SINGLE_LINE, "width": "50%"},
            {
                "id": "CACertificate",
                "label": "CA Certificate (Optional)",
                "type": FieldType.TEXT,
                "width": "100%"
            },
            {
                "id": "Echo",
                "label": "Enable SQL Logging",
                "type": FieldType.SINGLE_SELECT,
                "options": ["True", "False"],
                "width": "25%"
            }
        ]
    }

    def __init__(self, node: Node):
        self.node = node
        configuration = node.data.get("configuration") or {}
        self.db_type = configuration.get("DBType")
        self.host = configuration.get("Host")
        self.port = configuration.get("Port")
        self.database = configuration.get("Database")
        self.username = configuration.get("Username")
        self.password = configuration.get("Password")
        self.ca_cert = configuration.get("CACertificate")
        self.echo = str(configuration.get("Echo", "False")).lower() == "true"

    def build_connection_string(self):
        """Build a SQLAlchemy connection string based on database type."""
        driver_map = {
            "PostgreSQL": "postgresql+psycopg2",
            "MySQL": "mysql+pymysql",
            "SQLite": "sqlite",
            "MSSQL": "mssql+pyodbc",
            "Oracle": "oracle+cx_oracle",
        }

        driver = driver_map.get(self.db_type)
        if not driver:
            raise ValueError(f"Unsupported database type: {self.db_type}")

        if self.db_type == "SQLite":
            return f"sqlite:///{self.database or ':memory:'}"

        return f"{driver}://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

    def Run(self, connection, data):
        print("\n================= [DatabaseConnection] DEBUG START =================")
        print(f"DB Type: {self.db_type}")
        print(f"Host: {self.host}")
        print(f"Database: {self.database}")
        print(f"CA Cert Provided: {bool(self.ca_cert)}")

        try:
            connection_string = self.build_connection_string()
            safe_conn = connection_string.replace(self.password, "****") if self.password else connection_string

            connection_object = {
                "type": self.db_type,
                "connection_string": connection_string,
                "echo": self.echo,
                "ca_cert": self.ca_cert
            }

            self.node.LogEvent("Database Connection Created", data={"connection_string": safe_conn})
            self.node.SetTargetPinData("Connection", connection_object)

        except Exception as e:
            self.node.LogEvent("Database Connection Error", data={}, error=str(e))

        print("================= [DatabaseConnection] DEBUG END =================\n")
        return self.node.TriggerAll()
