import os

# 必须在 app.* 被导入前生效：测试全程使用 sqlite，且不跑真实种子
os.environ["SEED_ON_EMPTY"] = "false"
os.environ["DATABASE_URL"] = "sqlite://"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import database as db_module
from app.main import app
from app import main as main_module


@pytest.fixture()
def engine():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # lifespan 启动时的 ensure_schema 与依赖注入都指向同一个内存库
    db_module.engine = test_engine
    main_module.engine = test_engine
    yield test_engine
    test_engine.dispose()
    db_module.engine = None
    main_module.engine = None
