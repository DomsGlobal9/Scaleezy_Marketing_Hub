"""
Turning feedback into vectors.

Two paths, in order:

1. Whatever provider the workspace has routed to the EMBEDDING capability.
2. A deterministic local embedding, used when no provider is routed, the call
   fails, or the key is missing.

The fallback matters more than it looks: without it the training engine only
works on workspaces that have paid for an embedding provider, which would make
the whole of Phase 6 invisible in development and in tests. Hashed n-grams are
a poor semantic model but a perfectly good *repetition* detector, and
repetition is what a training rule is made of.

This module is the only place that knows how an embedding is represented.
"""
import hashlib
import logging
import math
import re
from typing import List, Sequence, Tuple

logger = logging.getLogger(__name__)

#: Dimensionality of the local fallback. Vectors are only ever compared with
#: others of the same length, so this never has to match a provider's size.
LOCAL_DIM = 256
LOCAL_MODEL = 'local-hashed-ngram-v1'

_TOKEN = re.compile(r"[a-z0-9']+")

# Words that appear in nearly every note and would otherwise dominate.
_STOPWORDS = frozenset(
    """a an and are as at be but by for from has have i in is it its of on or that the
    this to was were will with you your please make it's needs need should""".split()
)


def _tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall((text or '').lower()) if t not in _STOPWORDS]


def local_embedding(text: str) -> List[float]:
    """Signed hashing trick over unigrams and bigrams, L2-normalised."""
    vector = [0.0] * LOCAL_DIM
    tokens = _tokenize(text)
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]

    for gram in grams:
        digest = hashlib.blake2b(gram.encode('utf-8'), digest_size=8).digest()
        index = int.from_bytes(digest[:4], 'big') % LOCAL_DIM
        vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0

    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def embed(text: str, workspace=None) -> Tuple[List[float], str]:
    """
    Returns (vector, model_name). Never raises — a failed embedding must not
    cost a reviewer their verdict.
    """
    text = (text or '').strip()
    if not text:
        return [], ''

    if workspace is not None:
        try:
            from apps.ai.models import Capability
            from apps.ai.router import AIRouter

            result = AIRouter(workspace).dispatch(Capability.EMBEDDING, {'text': text})
            vector = [float(v) for v in (result.get('embedding') or [])]
            if vector:
                return _normalise(vector), result.get('model') or result.get('provider', '')
        except Exception as exc:  # noqa: BLE001 - fallback is the point
            logger.debug("Embedding provider unavailable, using local: %s", exc)

    return local_embedding(text), LOCAL_MODEL


def _normalise(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    return [float(v) / norm for v in vector] if norm else [float(v) for v in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Cosine similarity. Returns 0.0 for empty or mismatched vectors rather than
    raising — a workspace can hold vectors from two different models if the
    provider was switched mid-flight, and those simply do not compare.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot))
