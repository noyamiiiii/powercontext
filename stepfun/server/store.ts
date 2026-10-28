import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  FulltextIndexConfig,
  Schema,
  SeekdbClient,
  VectorIndexConfig,
  type Collection,
} from "seekdb";

export const EMBEDDING_DIMENSION = 512;
const COLLECTION_PREFIX = "kb_";

export interface KnowledgeBase {
  id: string;
  name: string;
  count: number;
  createdAt: string;
}

export interface KnowledgeDocument {
  id: string;
  text: string;
  embedding: number[];
  metadata?: Record<string, string | number | boolean>;
}

interface CatalogEntry {
  id: string;
  name: string;
  createdAt: string;
}

interface SearchRow {
  id: string;
  text: string;
  metadata: Record<string, unknown> | null;
  score: number | null;
}

export interface EmbeddedClientConfig {
  path: string;
  database: string;
}

export interface ServerClientConfig {
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
}

export type KnowledgeStoreConfig = EmbeddedClientConfig | ServerClientConfig;

export class KnowledgeStore {
  private readonly client: SeekdbClient;
  private readonly catalogPath: string;

  constructor(config: KnowledgeStoreConfig, catalogDirectory: string) {
    this.catalogPath = path.join(catalogDirectory, "catalog.json");
    this.client = new SeekdbClient(config);
  }

  async close(): Promise<void> {
    await this.client.close();
  }

  async ping(): Promise<void> {
    await this.client.execute("SELECT 1 AS ready");
  }

  async listKnowledgeBases(): Promise<KnowledgeBase[]> {
    const catalog = await this.readCatalog();
    const bases = await Promise.all(
      catalog.map(async (entry): Promise<KnowledgeBase | null> => {
        try {
          const collection = await this.client.getCollection({
            name: this.collectionName(entry.id),
            embeddingFunction: null,
          });
          return {
            ...entry,
            count: await collection.count(),
          };
        } catch {
          return null;
        }
      }),
    );
    return bases.filter((base): base is KnowledgeBase => base !== null);
  }

  async createKnowledgeBase(name: string): Promise<KnowledgeBase> {
    const normalized = name.trim();
    if (!normalized) {
      throw new Error("知识库名称不能为空");
    }
    const id = `${Date.now().toString(36)}_${crypto.randomUUID().replaceAll("-", "").slice(0, 8)}`;
    const collection = await this.createCollection(id);
    const entry: CatalogEntry = {
      id,
      name: normalized,
      createdAt: new Date().toISOString(),
    };
    const catalog = await this.readCatalog();
    catalog.push(entry);
    await this.writeCatalog(catalog);
    return {
      ...entry,
      count: await collection.count(),
    };
  }

  async deleteKnowledgeBase(id: string): Promise<void> {
    await this.client.deleteCollection(this.collectionName(id));
    const catalog = await this.readCatalog();
    await this.writeCatalog(catalog.filter((entry) => entry.id !== id));
  }

  async upsertDocuments(
    id: string,
    documents: KnowledgeDocument[],
  ): Promise<{ count: number }> {
    const collection = await this.getCollection(id);
    for (const document of documents) {
      if (document.embedding.length !== EMBEDDING_DIMENSION) {
        throw new Error(
          `文档 ${document.id} 的向量维度为 ${document.embedding.length}，应为 ${EMBEDDING_DIMENSION}`,
        );
      }
    }
    await collection.upsert({
      ids: documents.map((document) => document.id),
      documents: documents.map((document) => document.text),
      embeddings: documents.map((document) => document.embedding),
      metadatas: documents.map((document) => document.metadata ?? {}),
    });
    await collection.refresh_index();
    return { count: await collection.count() };
  }

  async search(
    id: string,
    query: string,
    queryEmbedding: number[],
    limit: number,
  ): Promise<SearchRow[]> {
    if (queryEmbedding.length !== EMBEDDING_DIMENSION) {
      throw new Error(
        `查询向量维度为 ${queryEmbedding.length}，应为 ${EMBEDDING_DIMENSION}`,
      );
    }
    const collection = await this.getCollection(id);
    const candidateCount = Math.max(limit * 5, 20);
    const results = await collection.hybridSearch({
      query: {
        whereDocument: { $contains: query },
        nResults: candidateCount,
      },
      knn: {
        queryEmbeddings: [queryEmbedding],
        nResults: candidateCount,
      },
      rank: { rrf: {} },
      nResults: limit,
      include: ["documents", "metadatas", "distances"],
    });
    const ids = results.ids[0] ?? [];
    const documents = results.documents?.[0] ?? [];
    const metadatas = results.metadatas?.[0] ?? [];
    const distances = results.distances?.[0] ?? [];
    return ids.map((resultId, index) => ({
      id: String(resultId),
      text: String(documents[index] ?? ""),
      metadata: (metadatas[index] as Record<string, unknown> | null) ?? null,
      score:
        distances[index] === null || distances[index] === undefined
          ? null
          : Number(distances[index]),
    }));
  }

  private async getCollection(id: string): Promise<Collection> {
    try {
      return await this.client.getCollection({
        name: this.collectionName(id),
        embeddingFunction: null,
      });
    } catch {
      throw new Error("知识库不存在");
    }
  }

  private async createCollection(id: string): Promise<Collection> {
    const schema = new Schema()
      .createIndex(new FulltextIndexConfig("ik", { ik_mode: "smart" }))
      .createIndex(
        new VectorIndexConfig({
          hnsw: {
            dimension: EMBEDDING_DIMENSION,
            distance: "cosine",
          },
          embeddingFunction: null,
        }),
      );
    return this.client.createCollection({
      name: this.collectionName(id),
      schema,
    });
  }

  private collectionName(id: string): string {
    if (!/^[a-z0-9_]+$/.test(id)) {
      throw new Error("知识库 ID 无效");
    }
    return `${COLLECTION_PREFIX}${id}`;
  }

  private async readCatalog(): Promise<CatalogEntry[]> {
    try {
      const content = await readFile(this.catalogPath, "utf8");
      const parsed = JSON.parse(content) as unknown;
      return Array.isArray(parsed) ? (parsed as CatalogEntry[]) : [];
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return [];
      }
      throw error;
    }
  }

  private async writeCatalog(catalog: CatalogEntry[]): Promise<void> {
    await mkdir(path.dirname(this.catalogPath), { recursive: true });
    await writeFile(
      this.catalogPath,
      `${JSON.stringify(catalog, null, 2)}\n`,
      "utf8",
    );
  }
}
