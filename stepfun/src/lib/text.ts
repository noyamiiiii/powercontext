import type { PreparedDocument } from "../types";

const MAX_CHUNK_LENGTH = 1_200;

export interface TextSource {
  name: string;
  text: string;
}

export function prepareDocuments(
  sources: TextSource[],
  importedAt = new Date().toISOString(),
): PreparedDocument[] {
  const documents: PreparedDocument[] = [];
  for (const source of sources) {
    const chunks = chunkText(source.text);
    chunks.forEach((text, index) => {
      documents.push({
        id: crypto.randomUUID(),
        text,
        metadata: {
          source: source.name,
          chunk: index + 1,
          importedAt,
        },
      });
    });
  }
  return documents;
}

export function chunkText(text: string): string[] {
  const normalized = text.replaceAll("\r\n", "\n").trim();
  if (!normalized) {
    return [];
  }
  const paragraphs = normalized
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const chunks: string[] = [];
  let current = "";

  for (const paragraph of paragraphs) {
    if (paragraph.length > MAX_CHUNK_LENGTH) {
      if (current) {
        chunks.push(current);
        current = "";
      }
      for (let start = 0; start < paragraph.length; start += MAX_CHUNK_LENGTH) {
        chunks.push(paragraph.slice(start, start + MAX_CHUNK_LENGTH).trim());
      }
      continue;
    }
    const candidate = current ? `${current}\n\n${paragraph}` : paragraph;
    if (candidate.length > MAX_CHUNK_LENGTH && current) {
      chunks.push(current);
      current = paragraph;
    } else {
      current = candidate;
    }
  }
  if (current) {
    chunks.push(current);
  }
  return chunks.filter(Boolean);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
