import sqlalchemy.types as types
from sqlalchemy.types import UserDefinedType


class MyType(types.UserDefinedType):
    cache_ok = True

    def __init__(self, precision=8):
        self.precision = precision

    def get_col_spec(self, **kw):
        return "MYTYPE(%s)" % self.precision

    def bind_processor(self, dialect):
        def process(value):
            return value

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            return value

        return process


class Box(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **kwargs):
        return "box"
