"""Тонкая обёртка над ClickHouse (clickhouse-connect)."""
from pathlib import Path

import clickhouse_connect

SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


class Db:
    def __init__(self, host="localhost", port=8123, database="analytics",
                 username="default", password=""):
        admin = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password)
        admin.command(f"CREATE DATABASE IF NOT EXISTS {database}")
        self.database = database
        self.client = clickhouse_connect.get_client(
            host=host, port=port, username=username, password=password,
            database=database)

    def create_schema(self):
        for stmt in SCHEMA.read_text(encoding="utf-8").split(";"):
            body = "\n".join(l for l in stmt.splitlines()
                             if not l.strip().startswith("--")).strip()
            if body:
                self.client.command(body)

    def drop(self):
        self.client.command(f"DROP DATABASE IF EXISTS {self.database}")

    def command(self, sql, parameters=None):
        return self.client.command(sql, parameters=parameters)

    def rows(self, sql, parameters=None):
        return list(self.client.query(sql, parameters=parameters).named_results())

    def insert(self, table, columns, data):
        if data:
            self.client.insert(table, data, column_names=columns)

    def tables(self):
        return {r["name"]: [c["name"] for c in self.rows(
            "SELECT name FROM system.columns WHERE database=%(d)s AND table=%(t)s",
            {"d": self.database, "t": r["name"]})]
            for r in self.rows("SELECT name FROM system.tables WHERE database=%(d)s",
                               {"d": self.database})}
