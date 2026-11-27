type AxisPair = [number, number];

/** Classical PCA via the centered Gram matrix. The chart has at most 21 vectors. */
export function projectEmbeddings(vectors: ArrayLike<number>[]): AxisPair[] {
  const count = vectors.length;
  if (!count) return [];
  const dimension = vectors[0].length;
  const mean = new Float64Array(dimension);
  for (const vector of vectors) {
    for (let i = 0; i < dimension; i++) mean[i] += vector[i] / count;
  }

  const centered = vectors.map(vector => Float64Array.from(mean, (average, i) => vector[i] - average));
  const gram = centered.map(row => Float64Array.from(centered, other => {
    let sum = 0;
    for (let i = 0; i < dimension; i++) sum += row[i] * other[i];
    return sum;
  }));
  const basis = centered.map((_, i) => Float64Array.from({ length: count }, (_, j) => Number(i === j)));

  // Jacobi rotations diagonalize the small symmetric Gram matrix.
  for (let sweep = 0; sweep < 32; sweep++) {
    let rotated = false;
    for (let p = 0; p < count - 1; p++) {
      for (let q = p + 1; q < count; q++) {
        const a = gram[p][q];
        if (Math.abs(a) < 1e-11) continue;
        rotated = true;
        const ratio = (gram[q][q] - gram[p][p]) / (2 * a);
        const turn = (ratio >= 0 ? 1 : -1) / (Math.abs(ratio) + Math.hypot(1, ratio));
        const cosine = 1 / Math.hypot(1, turn);
        const sine = turn * cosine;
        gram[p][p] -= turn * a;
        gram[q][q] += turn * a;
        gram[p][q] = gram[q][p] = 0;
        for (let i = 0; i < count; i++) {
          if (i !== p && i !== q) {
            const first = gram[i][p];
            const second = gram[i][q];
            gram[i][p] = gram[p][i] = cosine * first - sine * second;
            gram[i][q] = gram[q][i] = sine * first + cosine * second;
          }
          const first = basis[i][p];
          const second = basis[i][q];
          basis[i][p] = cosine * first - sine * second;
          basis[i][q] = sine * first + cosine * second;
        }
      }
    }
    if (!rotated) break;
  }

  const [first, second] = Array.from({ length: count }, (_, i) => i)
    .sort((a, b) => gram[b][b] - gram[a][a]);
  return basis.map(row => [
    row[first] * Math.sqrt(Math.max(0, gram[first][first])),
    second === undefined ? 0 : row[second] * Math.sqrt(Math.max(0, gram[second][second])),
  ]);
}
