import { Tokenizer } from "@huggingface/tokenizers";
import { env, InferenceSession, Tensor } from "onnxruntime-web/wasm";
import wasmModule from "onnxruntime-web/ort-wasm-simd-threaded.mjs?url";
import wasmBinary from "onnxruntime-web/ort-wasm-simd-threaded.wasm?url";
import type { Release } from "./assets";

export class Encoder {
  constructor(private tokenizer: Tokenizer, private session: InferenceSession,
    private dimension: number, private maxTokens: number) {}

  static async load(release: Release) {
    const config = release.manifest.dense;
    if (!config) throw new Error("The release has no semantic model");
    env.wasm.numThreads = 1;
    env.wasm.proxy = false;
    env.wasm.wasmPaths = { mjs: wasmModule, wasm: wasmBinary };
    const [tokenizer, options, graph] = await Promise.all([
      release.json<ConstructorParameters<typeof Tokenizer>[0]>("models/tokenizer.json"),
      release.json<ConstructorParameters<typeof Tokenizer>[1]>("models/tokenizer_config.json"),
      release.binary("models/model.onnx"),
    ]);
    const session = await InferenceSession.create(graph, { executionProviders: ["wasm"] });
    return new Encoder(new Tokenizer(tokenizer, options), session, config.dimension, config.max_tokens);
  }

  async query(text: string): Promise<Float32Array> {
    const { ids } = this.tokenizer.encode(text, { add_special_tokens: true });
    const truncated = ids.length > this.maxTokens ? [...ids.slice(0, this.maxTokens - 1), ids.at(-1)!] : ids;
    const shape = [1, truncated.length];
    const feeds: Record<string, Tensor> = {
      input_ids: new Tensor("int64", BigInt64Array.from(truncated, BigInt), shape),
      attention_mask: new Tensor("int64", new BigInt64Array(truncated.length).fill(1n), shape),
      token_type_ids: new Tensor("int64", new BigInt64Array(truncated.length), shape),
    };
    const result = await this.session.run(Object.fromEntries(this.session.inputNames.map(n => [n, feeds[n]])));
    const output = result.last_hidden_state;
    const hidden = output.data as Float32Array;
    if (hidden.length !== truncated.length * this.dimension) throw new Error("Unexpected model output shape");
    const mean = new Float64Array(this.dimension);
    for (let i = 0; i < truncated.length; i++) {
      for (let d = 0; d < this.dimension; d++) mean[d] += hidden[i * this.dimension + d];
    }
    const norm = Math.hypot(...mean);
    if (!Number.isFinite(norm) || norm <= 0) throw new Error("Non-finite or zero model embedding");
    return Float32Array.from(mean, value => value / norm);
  }
}

export function cosineVectors(vectors: DataView, query: Float32Array, rows: number) {
  if (vectors.byteLength !== rows * query.length * 4) throw new Error("Dense matrix shape does not match corpus");
  const result = new Map<number, number>();
  for (let row = 0; row < rows; row++) {
    let score = 0;
    for (let i = 0; i < query.length; i++) score += vectors.getFloat32((row * query.length + i) * 4, true) * query[i];
    if (!Number.isFinite(score)) throw new Error("Invalid dense score");
    result.set(row, score);
  }
  return result;
}
