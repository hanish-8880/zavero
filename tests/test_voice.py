import numpy as np

from zavero.voice import mic_level


def test_mic_level():
    assert mic_level(np.zeros(2400, dtype=np.int16)) == 0.0
    assert mic_level(np.array([], dtype=np.int16)) == 0.0
    quiet = mic_level((np.sin(np.arange(2400) / 5) * 500).astype(np.int16))
    speech = mic_level((np.sin(np.arange(2400) / 5) * 3000).astype(np.int16))
    assert 0 < quiet < speech <= 1.0
    assert mic_level(np.full(2400, 32000, dtype=np.int16)) == 1.0
