## Alembic setup
Example script how to configure alembic without installing `psycopg2`
or any other synchronous driver.

```python

import asyncio
import os
from logging.config import fileConfig

from alembic import context
# TODO: replace 2 lines below
from myapp.db import db  # noqa: F401
import myapp.models  # noqa: F401

# optionally use your settings object
url = os.getenv("SQLALCHEMY_DATABASE_URL")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)



def run_migrations_offline() -> None:
    context.configure(
        url=url,
        target_metadata=db.Model.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    def do_migrations(connection):
        context.configure(
            connection=connection,
            target_metadata=db.Model.metadata,
            dialect_opts={"paramstyle": "named"},
        )

        with context.begin_transaction():
            context.run_migrations()

    async with db.engine.connect() as connection:
        await connection.run_sync(do_migrations)


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

```
