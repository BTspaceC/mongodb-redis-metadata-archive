from scripts.import_data import clean_attributes, build_token


def test_clean_attributes():
    raw_nft = {
        "raw": {
            "metadata": {
                "attributes": [
                    {"trait_type": " background ", "value": " blue "},
                    {"trait_type": "HEAD", "value": "Crown"},
                    {"invalid_field": "test"}  # Should be filtered
                ]
            }
        }
    }
    attrs = clean_attributes(raw_nft)
    assert len(attrs) == 2
    assert attrs[0] == {"trait_type": "Background", "value": "blue"}
    assert attrs[1] == {"trait_type": "Head", "value": "Crown"}


def test_build_token_fills_missing_traits():
    raw_nft = {
        "tokenId": "100",
        "name": "Penguin #100",
        "image": {"cachedUrl": "https://cdn.example.com/100.png"},
        "raw": {
            "metadata": {
                "attributes": [
                    {"trait_type": "Background", "value": "Green"}
                ]
            }
        }
    }
    all_traits = ["Background", "Body", "Head"]
    doc = build_token("pudgypenguins", raw_nft, all_traits)

    assert doc["_id"] == "pudgypenguins:100"
    assert doc["token_id"] == 100
    assert doc["trait_count"] == 1  # only Background is non-None

    # Check that missing Body and Head are populated with 'None'
    attr_map = {a["trait_type"]: a["value"] for a in doc["attributes"]}
    assert attr_map["Background"] == "Green"
    assert attr_map["Body"] == "None"
    assert attr_map["Head"] == "None"
