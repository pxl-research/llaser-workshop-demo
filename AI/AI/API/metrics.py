from prometheus_client import Counter


total_queries = Counter("total_queries", "Total number of queries")
malicious_prompt_count = Counter("malicious_prompt_count", "Malicious prompts blocked")
prompt_defense_unavailable = Counter(
    "prompt_defense_unavailable", "Queries blocked because an enabled prompt defense was unavailable"
)
tokens_used = Counter("tokens_used", "Tokens consumed")
rerank_fallback = Counter("rerank_fallback", "Queries answered without reranking because the reranker failed")
