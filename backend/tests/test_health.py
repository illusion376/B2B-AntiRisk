from unittest.mock import MagicMock

import pytest
import redis
from fastapi import Response
from sqlalchemy.exc import SQLAlchemyError

from app.api.system import health


@pytest.mark.parametrize("database_ok,queue_ok", [(True, True), (False, True), (True, False), (False, False)])
def test_health_reports_dependency_readiness(monkeypatch, database_ok, queue_ok):
    db = MagicMock()
    if not database_ok:
        db.execute.side_effect = SQLAlchemyError("database unavailable")
    client = MagicMock()
    client.__enter__.return_value = client
    if queue_ok:
        client.ping.return_value = True
    else:
        client.ping.side_effect = redis.exceptions.TimeoutError("queue unavailable")
    connect = MagicMock(return_value=client)
    monkeypatch.setattr(redis.Redis, "from_url", connect)
    response = Response()

    payload = health(response, db)

    assert payload["database"] is database_ok
    assert payload["queue"] is queue_ok
    assert payload["status"] == ("ok" if database_ok and queue_ok else "degraded")
    assert response.status_code == (200 if database_ok and queue_ok else 503)
    assert connect.call_args.kwargs == {"socket_connect_timeout": 2, "socket_timeout": 2}
    assert db.rollback.call_count == (0 if database_ok else 1)
    client.__exit__.assert_called_once()
