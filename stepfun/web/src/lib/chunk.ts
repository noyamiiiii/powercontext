/**
 * Text splitting for import.
 *
 * Users paste prose or drop .md/.txt files; we split on blank lines and, when a
 * single block is too long, on sentence boundaries. Chunks stay small enough
 * for the 512-token window of the embedding model while keeping paragraphs
 * semantically intact (which matters more for retrieval quality than perfectly
 * equal chunk sizes).
 */

const SENTENCE_END = /(?<=[。！？!?；;\n])|(?<=\.\s)/;

export interface ChunkOptions {
  maxChars?: number;
  minChars?: number;
}

export function chunkText(input: string, options: ChunkOptions = {}): string[] {
  const maxChars = options.maxChars ?? 400;
  const minChars = options.minChars ?? 24;

  const normalized = input.replace(/\r\n/g, "\n").replace(/\t/g, " ").trim();
  if (!normalized) return [];

  const blocks = normalized
    .split(/\n{2,}/)
    .map((block) => block.replace(/[ ]{2,}/g, " ").trim())
    .filter(Boolean);

  const chunks: string[] = [];
  for (const block of blocks) {
    if (block.length <= maxChars) {
      chunks.push(block);
      continue;
    }
    // Long block: pack sentences until the budget is reached.
    let buffer = "";
    for (const piece of block.split(SENTENCE_END)) {
      const sentence = piece.trim();
      if (!sentence) continue;
      if (buffer.length + sentence.length <= maxChars) {
        buffer += sentence;
        continue;
      }
      if (buffer.trim()) chunks.push(buffer.trim());
      buffer = sentence;
    }
    if (buffer.trim()) chunks.push(buffer.trim());
  }

  // Drop fragments that carry no retrievable content.
  return chunks.filter((chunk) => chunk.length >= minChars || chunks.length <= 3);
}

export function makeDocId(prefix: string, index: number): string {
  return `${prefix}-${String(index).padStart(4, "0")}`;
}
