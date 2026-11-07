import pytest

from app.agents.worker_guard import detect_worker_count, validate_single_worker_relay


def test_worker_guard_accepts_single_worker_from_env_or_cli():
    assert detect_worker_count({"WEB_CONCURRENCY": "1"}, []) == 1
    assert detect_worker_count({}, ["--workers", "1"]) == 1
    assert detect_worker_count({"GUNICORN_CMD_ARGS": "--workers=1"}, []) == 1
    validate_single_worker_relay({"WEB_CONCURRENCY": "1"}, [])


@pytest.mark.parametrize(
    "environ,argv",
    [
        ({"WEB_CONCURRENCY": "2"}, []),
        ({"UVICORN_WORKERS": "4"}, []),
        ({"GUNICORN_CMD_ARGS": "-w 3"}, []),
        ({}, ["--workers", "2"]),
        ({"WEB_CONCURRENCY": "1"}, ["--workers", "3"]),
    ],
)
def test_worker_guard_rejects_multi_worker_launch(environ, argv):
    with pytest.raises(RuntimeError, match="process-local"):
        validate_single_worker_relay(environ, argv)


def test_worker_guard_rejects_invalid_worker_environment():
    with pytest.raises(RuntimeError, match="positive integer"):
        detect_worker_count({"WEB_CONCURRENCY": "many"}, [])
