import numpy as np
import pytest

from openphoto.analysis import LocalModels


def test_cpu_encoder_normalizes_inference_tensor_without_inplace_mutation(tmp_path):
    torch = pytest.importorskip("torch")
    models = LocalModels(tmp_path)
    models._loaded.add("clip")

    class Encoder:
        def encode_image(self, image):
            return torch.ones((1,512))

    models.clip = Encoder()
    models.preprocess = lambda image: torch.zeros((3,224,224))
    vector, _ = models.embedding(np.zeros((64,64,3), np.uint8))
    assert len(vector) == 512
    assert abs(np.linalg.norm(vector)-1) < 1e-6
