"""Re-embed all ABP memories from 768-dim to 1024-dim voyage-4-nano.

Run this once after migrating to the shared infrastructure:

    cd /home/ben/Dev/AgentBenchPlatform
    source .venv/bin/activate
    python scripts/migrate_embeddings.py

Requires:
  - Shared MongoDB running on port 27017
  - Shared embeddings service running on port 8001
"""

import asyncio

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URI = "mongodb://localhost:27017/?directConnection=true&replicaSet=rs0"
DB_NAME = "agentbenchplatform"
EMBEDDING_URL = "http://localhost:8001/v1/embeddings"
BATCH_SIZE = 32


async def main():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    memories = db["memories"]

    # Find all memories with content
    cursor = memories.find({"content": {"$exists": True, "$ne": ""}})
    docs = await cursor.to_list(length=None)

    print(f"Found {len(docs)} memories to re-embed")

    if not docs:
        print("No memories to migrate. Done.")
        client.close()
        return

    async with httpx.AsyncClient(timeout=120.0) as http:
        for i in range(0, len(docs), BATCH_SIZE):
            batch = docs[i : i + BATCH_SIZE]
            texts = [doc["content"] for doc in batch]

            resp = await http.post(EMBEDDING_URL, json={"input": texts})
            resp.raise_for_status()
            embeddings = [item["embedding"] for item in resp.json()["data"]]

            for doc, emb in zip(batch, embeddings):
                await memories.update_one(
                    {"_id": doc["_id"]}, {"$set": {"embedding": emb}}
                )

            print(f"  Re-embedded {min(i + BATCH_SIZE, len(docs))}/{len(docs)}")

    # Recreate vector search index with 1024 dimensions
    try:
        await db.command(
            {"dropSearchIndex": "memories", "name": "memory_vector_index"}
        )
        print("Dropped old vector search index")
    except Exception as e:
        print(f"No existing index to drop: {e}")

    await db.command(
        {
            "createSearchIndexes": "memories",
            "indexes": [
                {
                    "name": "memory_vector_index",
                    "type": "vectorSearch",
                    "definition": {
                        "fields": [
                            {
                                "type": "vector",
                                "path": "embedding",
                                "numDimensions": 1024,
                                "similarity": "cosine",
                            }
                        ]
                    },
                }
            ],
        }
    )
    print("Created new 1024-dim vector search index")

    client.close()
    print("Migration complete!")


asyncio.run(main())
