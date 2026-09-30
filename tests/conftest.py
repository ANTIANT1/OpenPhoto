
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from openphoto.api import create_app
from openphoto.service import Pipeline


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "Съёмка с пробелами"
    source.mkdir()
    for i in range(4):
        y, x = np.mgrid[0:240, 0:320]
        array = np.stack([(x + i*25) % 256, (y + i*13) % 256, (x//2+y//2) % 256], axis=-1).astype(np.uint8)
        Image.fromarray(array).save(source / f"кадр {i}.jpg", quality=95)
    project = tmp_path / "project"
    app = create_app(project, token="test-token", start_worker=False)
    app.state.catalog.set_setting("models_directory", str(tmp_path / "no-models"))
    with TestClient(app, headers={"X-OpenPhoto-Token": "test-token"}) as client:
        yield client, Pipeline(project), source, project


def import_all(client, pipeline, source):
    response = client.post("/api/import", json={"paths": [str(source)], "shoot_name": "Тест"})
    assert response.status_code == 200, response.text
    pipeline.run(response.json()["job_id"])
    return client.get("/api/photos").json()["photos"]
