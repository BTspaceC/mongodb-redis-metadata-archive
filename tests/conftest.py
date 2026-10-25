import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import mongomock
import fakeredis
from starlette.testclient import TestClient

# Mock MongoDB and Redis before importing app
import app.db

fake_mongo = mongomock.MongoClient()
fake_db = fake_mongo["nft_archive_test"]
fake_rds = fakeredis.FakeRedis(decode_responses=True)

# Patch app.db
app.db.mongo = fake_mongo
app.db.db = fake_db
app.db.rds = fake_rds

# Patch app.cache
import app.cache
app.cache.rds = fake_rds

# Patch routers
import app.routers.tokens
import app.routers.rank
import app.routers.stats
import app.routers.admin

app.routers.tokens.db = fake_db
app.routers.tokens.rds = fake_rds
app.routers.rank.db = fake_db
app.routers.rank.rds = fake_rds
app.routers.stats.db = fake_db
app.routers.stats.rds = fake_rds
app.routers.admin.db = fake_db
app.routers.admin.rds = fake_rds

from app.main import app as fastapi_app


@pytest.fixture(autouse=True)
def clean_databases():
    """Ensure clean slate before each test run."""
    fake_db.tokens.delete_many({})
    fake_db.collections.delete_many({})
    fake_db.trait_stats.delete_many({})
    fake_rds.flushall()
    yield


@pytest.fixture
def client():
    return TestClient(fastapi_app)


@pytest.fixture
def sample_tokens():
    tokens = [
        {
            "_id": "pudgypenguins:1",
            "collection_id": "pudgypenguins",
            "token_id": 1,
            "name": "Pudgy Penguin #1",
            "image": {
                "cached": "https://nft2-cdn.alchemy.com/1.png",
                "thumb": "https://nft2-cdn.alchemy.com/thumb_1.png",
                "local": None
            },
            "attributes": [
                {"trait_type": "Background", "value": "Blue", "count": 10, "frequency": 0.1},
                {"trait_type": "Body", "value": "Normal", "count": 50, "frequency": 0.5}
            ],
            "trait_count": 2,
            "rarity": {"score": 12.0, "rank": 1, "method": "statistical"},
            "transfers": [],
            "tags": ["showcase"],
            "notes": ""
        },
        {
            "_id": "pudgypenguins:2",
            "collection_id": "pudgypenguins",
            "token_id": 2,
            "name": "Pudgy Penguin #2",
            "image": {
                "cached": "https://nft2-cdn.alchemy.com/2.png",
                "thumb": "https://nft2-cdn.alchemy.com/thumb_2.png",
                "local": None
            },
            "attributes": [
                {"trait_type": "Background", "value": "Red", "count": 20, "frequency": 0.2},
                {"trait_type": "Body", "value": "Normal", "count": 50, "frequency": 0.5}
            ],
            "trait_count": 2,
            "rarity": {"score": 7.0, "rank": 2, "method": "statistical"},
            "transfers": [],
            "tags": [],
            "notes": ""
        }
    ]
    fake_db.tokens.insert_many(tokens)
    fake_db.collections.insert_one({
        "_id": "pudgypenguins",
        "name": "Pudgy Penguins",
        "token_count": 2,
        "trait_types": ["Background", "Body"]
    })
    return tokens
