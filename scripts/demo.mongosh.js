// =====================================================================
// MongoDB Core Operations, Multikey Index & Performance Benchmark
// Usage: mongosh nft_archive scripts/demo.mongosh.js
// =====================================================================

db = db.getSiblingDB("nft_archive");

print("\n[1] Testing Schema Flexibility (Dynamic attribute extension)...");
db.tokens.insertOne({
  _id: "benchmark:test:1",
  collection_id: "benchmark",
  token_id: 1,
  name: "Benchmark Token #1",
  level: 5,
  attributes: [{ trait_type: "Element", value: "Fire" }]
});
print(" -> Insert succeeded: Dynamic schema validated.");

print("\n[2] Testing JSON Schema Enforcement (Rejecting invalid document)...");
try {
  db.tokens.insertOne({
    _id: "benchmark:test:invalid",
    collection_id: "benchmark",
    token_id: 2
    // Missing required 'attributes' array
  });
  print(" -> Failed: Schema validation did not catch invalid doc.");
} catch (e) {
  print(" -> Success: Schema constraint strictly enforced (rejected as expected).");
}

print("\n[3] Testing Multikey Index Intersection Query ($all + $elemMatch)...");
var start = new Date();
var results = db.tokens.find({
  collection_id: "pudgypenguins",
  attributes: {
    $all: [
      { $elemMatch: { trait_type: "Background", value: "Beige" } },
      { $elemMatch: { trait_type: "Head", value: "Headband" } }
    ]
  }
}, { token_id: 1, name: 1, _id: 0 }).toArray();
var durationMs = new Date() - start;
print(" -> Matches found: " + results.length + " items (Query latency: " + durationMs + "ms)");

print("\n[4] Query Execution Plan & Index Stats (EXPLAIN)...");
var exp = db.tokens.find({
  collection_id: "pudgypenguins",
  "attributes.trait_type": "Body",
  "attributes.value": "Kimono"
}).explain("executionStats");
print(" -> Stage: " + exp.executionStats.executionStages.stage);
print(" -> Docs Examined vs Docs Returned: " + exp.executionStats.totalDocsExamined + " / " + exp.executionStats.nReturned);

print("\n[5] Cleaning up benchmark artifacts...");
db.tokens.deleteMany({ collection_id: "benchmark" });
print(" -> Environment restored successfully.\n");
