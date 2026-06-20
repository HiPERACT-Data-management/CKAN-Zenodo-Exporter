from dbutils.pooled_db import PooledDB
import pymysql
import configs

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        db_config = configs.get_db_config()
        _pool = PooledDB(
            creator=pymysql,
            maxconnections=10,
            mincached=1,
            maxcached=5,
            blocking=True,
            **db_config
        )
    return _pool


def get_connection():
    """Return a pooled DB connection. Call .close() to return it to the pool."""
    return _get_pool().connection()
