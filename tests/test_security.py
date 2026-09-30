from fastapi.testclient import TestClient

from openphoto.api import create_app


def test_session_origin_host_and_csrf(tmp_path):
    app = create_app(tmp_path, token="secret", start_worker=False)
    with TestClient(app) as client:
        assert client.get('/api/status').status_code == 401
        assert client.get('/api/status', headers={'x-openphoto-token':'secret'}).status_code == 200
        assert client.get('/api/status', headers={'x-openphoto-token':'secret','Origin':'https://evil.example'}).status_code == 403
        assert client.get('/api/status', headers={'x-openphoto-token':'secret','Host':'evil.example'}).status_code == 403
        client.cookies.set('openphoto_session','secret')
        assert client.get('/api/status').status_code == 200
        assert client.post('/api/ranker/train').status_code == 401
        assert client.get('/api/references/../../catalog.sqlite').status_code != 200
