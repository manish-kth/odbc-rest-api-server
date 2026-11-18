"""A stand-in for a pyodbc connection, so tests need no ODBC driver."""

import pyodbc


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []
        self.params = []
        self.description = [("ID",)]

    def execute(self, sql, *params):
        self.executed.append(sql)
        self.params.append(params)
        return self

    def fetchone(self):
        return (len(self._rows),)

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def fetchmany(self, size):
        rows, self._rows = self._rows[:size], self._rows[size:]
        return rows

    def skip(self, count):
        self._rows = self._rows[count:]

    def tables(self, tableType=None):
        return []


class FakeConnection:
    """`dbms` and `quote` are what the driver reports through SQLGetInfo;
    None makes that call fail, as it does on drivers that do not answer."""

    def __init__(self, rows=(), dbms=None, quote=None):
        self.cursor_obj = FakeCursor(rows)
        self.closed = False
        self._info = {pyodbc.SQL_DBMS_NAME: dbms, pyodbc.SQL_IDENTIFIER_QUOTE_CHAR: quote}

    def getinfo(self, code):
        value = self._info.get(code)
        if value is None:
            raise pyodbc.Error("HY096", "Information type out of range")
        return value

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True
