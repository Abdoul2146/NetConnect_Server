# In C:\Users\abdul\Desktop\fastapi\fastapi\netcom\app\alembic\env.py

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add your project root to sys.path FIRST
# This allows 'app' and its modules (like app.database, app.models) to be imported
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

# Now, import from your application's database module
from app.database import SQLALCHEMY_DATABASE_URL # <--- Import the URL directly
from app.models import Base as AppModelsBase # Import Base from your models.py

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python's logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# Set the SQLAlchemy URL from your database.py, overriding alembic.ini's setting
# This ensures Alembic uses the exact same DB path as your FastAPI app.
config.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL) # <--- CRUCIAL CHANGE

# Add your model's metadata here for autogenerate support
# (Ensure AppModelsBase is the Base class your models inherit from)
target_metadata = AppModelsBase.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
