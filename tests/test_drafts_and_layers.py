from conftest import import_all


def test_draft_recovers_without_changing_export_recipe_and_stale_draft_is_rejected(workspace):
    client, pipeline, source, _ = workspace
    photo = import_all(client, pipeline, source)[0]
    url = f"/api/photos/{photo['id']}"
    recipe = client.get(url).json()["recipe"]
    recipe["color"]["warmth"] = .12
    body = {"recipe": recipe, "expected_revision": 0}
    assert client.put(url + "/draft", json=body).status_code == 200
    current = client.get(url).json()
    assert current["draft"]["color"]["warmth"] == .12
    assert current["recipe"]["color"]["warmth"] == 0
    assert current["revision"] == 0
    assert client.put(url + "/recipe", json=body).status_code == 200
    assert client.get(url).json()["draft"] is None
    assert client.put(url + "/draft", json=body).status_code == 409


def test_group_settings_win_over_shoot_and_manual_over_group(workspace):
    client, pipeline, source, _ = workspace
    photos = import_all(client, pipeline, source)
    a, b, c, d = [p["id"] for p in photos]
    client.post("/api/groups", json={"photo_ids": [a,b,c], "action": "merge"})
    recipe = client.get(f"/api/photos/{a}").json()["recipe"]
    recipe["color"]["warmth"] = .08
    request = {"photo_ids": [a], "source_photo_id": a, "recipe": recipe, "sections": ["color"], "scope": "group"}
    assert client.post("/api/recipes/batch", json=request).status_code == 200
    manual = client.get(f"/api/photos/{b}").json()
    manual["recipe"]["color"]["warmth"] = .15
    client.put(f"/api/photos/{b}/recipe", json={"recipe": manual["recipe"], "expected_revision": manual["revision"]})
    recipe["color"]["warmth"] = -.1
    assert client.post("/api/recipes/batch", json={**request, "scope": "shoot"}).status_code == 200
    assert client.get(f"/api/photos/{b}").json()["recipe"]["color"]["warmth"] == .15
    assert client.get(f"/api/photos/{c}").json()["recipe"]["color"]["warmth"] == .08
    assert client.get(f"/api/photos/{d}").json()["recipe"]["color"]["warmth"] == -.1
