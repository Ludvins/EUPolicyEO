from pathlib import Path

import numpy as np

from .storage import file_hash

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MAX_TOKENS = 256
DIMENSION = 384
FILES = ("model.onnx", "tokenizer.json")
PINNED_HASHES = {
    "model.onnx": "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452",
    "tokenizer.json": "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037",
    "tokenizer_config.json": "acb92769e8195aabd29b7b2137a9e6d6e25c476a4f15aa4355c233426c61576b",
}


class Encoder:
    """Mean-pool the ONNX hidden states with the attention mask, then L2-normalize."""

    def __init__(self, root: Path, threads: int = 4, batch: int = 24):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if PINNED_HASHES and any(
            file_hash(root / name) != sha for name, sha in PINNED_HASHES.items()
        ):
            raise ValueError("encoder does not match pinned artifact hashes")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        opts.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            root / "model.onnx", sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.inputs = [value.name for value in self.session.get_inputs()]
        self.tokenizer = Tokenizer.from_file(str(root / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=MAX_TOKENS)
        self.tokenizer.enable_padding()
        self.batch = batch

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for offset in range(0, len(texts), self.batch):
            tokens = self.tokenizer.encode_batch(texts[offset : offset + self.batch])
            mask = np.asarray([t.attention_mask for t in tokens], dtype=np.int64)
            inputs = {
                "input_ids": [t.ids for t in tokens],
                "attention_mask": mask,
                "token_type_ids": [t.type_ids for t in tokens],
            }
            states = self.session.run(
                ["last_hidden_state"],
                {name: np.asarray(inputs[name], dtype=np.int64) for name in self.inputs},
            )[0]
            mean = (states * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            norms = np.linalg.norm(mean, axis=1, keepdims=True)
            if not np.all(np.isfinite(mean)) or (norms == 0).any():
                raise ValueError("invalid encoder output")
            vectors.extend(mean / norms)
        return np.asarray(vectors, dtype=np.float32).reshape(-1, DIMENSION)
